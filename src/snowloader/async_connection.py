"""Async ServiceNow API connection handler for snowloader.

This module provides AsyncSnowConnection, an aiohttp-backed counterpart to
:class:`snowloader.SnowConnection`. It mirrors the public surface of the sync
class but adds bounded concurrent pagination so large extractions complete
in minutes instead of hours.

Key differences vs SnowConnection:

    - All I/O methods are coroutines (``aget_records``, ``aget_record``).
    - Pagination dispatches multiple page fetches concurrently, controlled by
      the ``concurrency`` constructor argument.
    - Use as an async context manager::

        async with AsyncSnowConnection(...) as conn:
            async for rec in conn.aget_records("incident"):
                ...

Author: Roni Das
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime
from types import TracebackType
from typing import Any, cast

try:
    import aiohttp
except ImportError as exc:
    raise ImportError(
        "aiohttp is required for the async API. Install it with: pip install snowloader[async]"
    ) from exc

from snowloader.connection import SnowConnectionError

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BACKOFF = 1.0
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
_MAX_PAGE_SIZE = 10000
_MIN_PAGE_SIZE = 1
_DEFAULT_CONCURRENCY = 16

_INSTANCE_URL_PATTERN = re.compile(r"^https?://[a-zA-Z0-9][-a-zA-Z0-9.]+\.[a-zA-Z]{2,}")


class AsyncSnowConnection:
    """Async session against one ServiceNow instance.

    Supports the same four authentication modes as :class:`SnowConnection`:
    bearer token, OAuth client credentials, OAuth password grant, basic auth.

    Args:
        instance_url: Full URL of the ServiceNow instance.
        username: ServiceNow user account.
        password: Password for the user account.
        client_id: OAuth client ID.
        client_secret: OAuth client secret.
        token: Pre-obtained Bearer token.
        page_size: Records per API call. Defaults to 500 (vs 100 in sync) since
            the async path is fast enough that fewer round trips wins.
        timeout: HTTP request timeout in seconds. Defaults to 120.
        max_retries: Retry attempts for transient failures.
        retry_backoff: Base delay between retries (seconds).
        display_value: Controls ``sysparm_display_value``. Defaults to ``"true"``.
        proxy: Optional proxy URL.
        verify_ssl: SSL verification. Defaults to True.
        concurrency: Maximum number of concurrent page fetches. Defaults to 16.

    Raises:
        SnowConnectionError: If credentials or URL are invalid.

    Example:
        >>> async def run():
        ...     async with AsyncSnowConnection(
        ...         instance_url="https://mycompany.service-now.com",
        ...         username="admin",
        ...         password="pass",
        ...         concurrency=16,
        ...     ) as conn:
        ...         async for rec in conn.aget_records("incident", query="active=true"):
        ...             print(rec["number"])
    """

    def __init__(
        self,
        instance_url: str,
        username: str | None = None,
        password: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        token: str | None = None,
        page_size: int = 500,
        timeout: int = 120,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_backoff: float = _DEFAULT_RETRY_BACKOFF,
        display_value: str = "true",
        proxy: str | None = None,
        verify_ssl: bool = True,
        concurrency: int = _DEFAULT_CONCURRENCY,
    ) -> None:
        if not instance_url or not instance_url.strip():
            raise SnowConnectionError(
                "instance_url must not be empty.",
                detail="Provide a URL like https://mycompany.service-now.com",
            )

        cleaned_url = instance_url.rstrip("/")
        if not _INSTANCE_URL_PATTERN.match(cleaned_url):
            raise SnowConnectionError(
                f"instance_url '{cleaned_url}' is not a valid HTTP(S) URL.",
                detail="URL must start with http:// or https:// followed by a valid domain.",
            )

        if not _MIN_PAGE_SIZE <= page_size <= _MAX_PAGE_SIZE:
            raise SnowConnectionError(
                f"page_size must be between {_MIN_PAGE_SIZE} and {_MAX_PAGE_SIZE}, "
                f"got {page_size}.",
            )

        if timeout <= 0:
            raise SnowConnectionError(f"timeout must be positive, got {timeout}.")

        if display_value not in ("true", "false", "all"):
            raise SnowConnectionError(
                f"display_value must be 'true', 'false', or 'all', got '{display_value}'.",
            )

        if concurrency < 1:
            raise SnowConnectionError(
                f"concurrency must be >= 1, got {concurrency}.",
            )

        self.instance_url = cleaned_url
        self.page_size = page_size
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.display_value = display_value
        self.concurrency = concurrency
        self._proxy = proxy
        self._verify_ssl = verify_ssl
        self._session: aiohttp.ClientSession | None = None
        self._token_lock = asyncio.Lock()

        if token:
            self.auth_type = "bearer"
            self._access_token: str | None = token
            self._username: str | None = None
            self._password: str | None = None
            self._client_id: str | None = None
            self._client_secret: str | None = None
            logger.info("Configured bearer token auth for %s", self.instance_url)
        elif client_id and client_secret and not username:
            self.auth_type = "client_credentials"
            self._client_id = client_id
            self._client_secret = client_secret
            self._username = None
            self._password = None
            self._access_token = None
            logger.info("Configured OAuth client credentials for %s", self.instance_url)
        elif client_id and client_secret and username and password:
            self.auth_type = "oauth"
            self._client_id = client_id
            self._client_secret = client_secret
            self._username = username
            self._password = password
            self._access_token = None
            logger.info("Configured OAuth password grant for %s", self.instance_url)
        elif username and password:
            self.auth_type = "basic"
            self._access_token = None
            self._username = username
            self._password = password
            self._client_id = None
            self._client_secret = None
            logger.info("Configured basic auth for %s", self.instance_url)
        else:
            raise SnowConnectionError(
                "AsyncSnowConnection requires credentials. Provide one of:\n"
                "  - token (pre-obtained bearer token)\n"
                "  - client_id + client_secret (OAuth client credentials)\n"
                "  - client_id + client_secret + username + password (OAuth password grant)\n"
                "  - username + password (basic auth)",
            )

    async def __aenter__(self) -> AsyncSnowConnection:
        await self._ensure_session()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=self.concurrency * 2,
                ssl=self._verify_ssl,
            )
            timeout_cfg = aiohttp.ClientTimeout(total=self.timeout)
            auth = None
            if self.auth_type == "basic" and self._username and self._password:
                auth = aiohttp.BasicAuth(self._username, self._password)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout_cfg,
                auth=auth,
                headers={"Accept": "application/json"},
            )
        return self._session

    async def _ensure_token(self) -> None:
        if self.auth_type not in ("oauth", "client_credentials"):
            return
        async with self._token_lock:
            if self._access_token is None:
                self._access_token = await self._acquire_oauth_token()

    async def _acquire_oauth_token(self) -> str:
        token_url = f"{self.instance_url}/oauth_token.do"
        if self.auth_type == "client_credentials":
            assert self._client_id and self._client_secret
            grant_data = {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        else:
            assert self._client_id and self._client_secret
            assert self._username and self._password
            grant_data = {
                "grant_type": "password",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "username": self._username,
                "password": self._password,
            }

        session = await self._ensure_session()
        try:
            async with session.post(
                token_url,
                data=grant_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                proxy=self._proxy,
            ) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    raise SnowConnectionError(
                        f"OAuth token request returned {resp.status}.",
                        status_code=resp.status,
                        detail=body,
                    )
                try:
                    data = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    raise SnowConnectionError(
                        "OAuth token response was not valid JSON.",
                        detail=body,
                    ) from exc
        except aiohttp.ClientError as exc:
            raise SnowConnectionError(
                f"OAuth token request failed: {exc}",
            ) from exc

        access_token = data.get("access_token")
        if not access_token:
            raise SnowConnectionError(
                "OAuth response did not contain an access_token.",
                detail=f"Response keys: {list(data.keys())}",
            )
        return str(access_token)

    def _build_query_params(
        self,
        query: str | None = None,
        fields: list[str] | None = None,
        since: datetime | None = None,
    ) -> dict[str, str]:
        params: dict[str, str] = {
            "sysparm_limit": str(self.page_size),
            "sysparm_display_value": self.display_value,
        }
        query_parts: list[str] = []
        if query:
            query_parts.append(query)
        if since:
            timestamp = since.strftime("%Y-%m-%d %H:%M:%S")
            query_parts.append(f"sys_updated_on>{timestamp}")
        query_parts.append("ORDERBYsys_created_on")
        params["sysparm_query"] = "^".join(query_parts)
        if fields:
            params["sysparm_fields"] = ",".join(fields)
        return params

    async def _request(
        self,
        method: str,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        await self._ensure_session()
        await self._ensure_token()

        headers: dict[str, str] = {}
        if self.auth_type in ("oauth", "client_credentials", "bearer"):
            headers["Authorization"] = f"Bearer {self._access_token}"

        attempt = 0
        backoff = self.retry_backoff
        last_status: int | None = None
        last_body = ""

        while True:
            try:
                assert self._session is not None
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    proxy=self._proxy,
                ) as resp:
                    last_status = resp.status
                    if resp.status == 401 and self.auth_type in ("oauth", "client_credentials"):
                        # Token expired, refresh once
                        self._access_token = None
                        await self._ensure_token()
                        headers["Authorization"] = f"Bearer {self._access_token}"
                        if attempt < self.max_retries:
                            attempt += 1
                            continue

                    if resp.status in _RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after and retry_after.isdigit():
                            wait = float(retry_after)
                        else:
                            wait = backoff
                        logger.warning(
                            "Got %d from %s, retrying in %.1fs (attempt %d/%d)",
                            resp.status,
                            url,
                            wait,
                            attempt + 1,
                            self.max_retries,
                        )
                        await asyncio.sleep(wait)
                        attempt += 1
                        backoff *= 2
                        continue

                    last_body = await resp.text()
                    if resp.status >= 400:
                        raise SnowConnectionError(
                            f"API returned {resp.status} for {method} {url}",
                            status_code=resp.status,
                            detail=last_body,
                        )

                    try:
                        parsed = await resp.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError) as exc:
                        raise SnowConnectionError(
                            f"API returned non-JSON response for {method} {url}",
                            status_code=resp.status,
                            detail=last_body,
                        ) from exc

                    if not isinstance(parsed, dict):
                        # Some ServiceNow paths can return ``null`` or a list
                        # under transient load. Treat anything that is not a
                        # JSON object as an empty result so downstream code
                        # does not crash on ``data.get(...)``.
                        logger.warning(
                            "API returned non-object JSON for %s %s (type=%s); "
                            "treating as empty result.",
                            method,
                            url,
                            type(parsed).__name__,
                        )
                        return {"result": []}
                    return cast(dict[str, Any], parsed)
            except aiohttp.ClientError as exc:
                if attempt < self.max_retries:
                    logger.warning(
                        "Network error on %s: %s (attempt %d/%d)",
                        url,
                        exc,
                        attempt + 1,
                        self.max_retries,
                    )
                    await asyncio.sleep(backoff)
                    attempt += 1
                    backoff *= 2
                    continue
                raise SnowConnectionError(
                    f"Network error on {method} {url}: {exc}",
                    status_code=last_status,
                    detail=last_body,
                ) from exc

    async def aget_count(
        self,
        table: str,
        query: str | None = None,
        since: datetime | None = None,
    ) -> int:
        """Return the total record count for a table query.

        Uses the ``/api/now/stats/<table>`` endpoint, which is much cheaper
        than fetching records and is required for concurrent pagination
        (we need to know how many pages to dispatch).
        """
        if not table or not table.strip():
            raise SnowConnectionError("table name must not be empty.")

        params: dict[str, str] = {"sysparm_count": "true"}
        query_parts: list[str] = []
        if query:
            query_parts.append(query)
        if since:
            timestamp = since.strftime("%Y-%m-%d %H:%M:%S")
            query_parts.append(f"sys_updated_on>{timestamp}")
        if query_parts:
            params["sysparm_query"] = "^".join(query_parts)

        url = f"{self.instance_url}/api/now/stats/{table}"
        data = await self._request("GET", url, params=params)
        result = data.get("result", {})
        stats = result.get("stats", {}) if isinstance(result, dict) else {}
        try:
            return int(stats.get("count", 0))
        except (ValueError, TypeError):
            return 0

    async def aget_records(
        self,
        table: str,
        query: str | None = None,
        fields: list[str] | None = None,
        since: datetime | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        """Stream records from a table with concurrent pagination.

        Pre-fetches the total count to plan how many pages to dispatch.
        Up to ``concurrency`` pages are fetched in parallel and yielded in
        completion order (NOT sys_created_on order). For ordered output,
        sort the results client-side after collecting them.

        Args:
            table: ServiceNow table name.
            query: Encoded query string. ``ORDERBYsys_created_on`` is appended.
            fields: List of field names to request, or None for all.
            since: Delta sync cutoff.

        Yields:
            One record dict at a time.
        """
        if not table or not table.strip():
            raise SnowConnectionError("table name must not be empty.")

        # Build full query (including since) for both count and pagination
        params = self._build_query_params(query=query, fields=fields, since=since)
        full_query = params.get("sysparm_query")

        # Total count
        total = await self.aget_count(table, query=full_query)
        if total == 0:
            logger.info("No records match the query for '%s'", table)
            return

        page_count = (total + self.page_size - 1) // self.page_size
        logger.info(
            "Async fetch from '%s': %d records, %d pages, concurrency=%d",
            table,
            total,
            page_count,
            self.concurrency,
        )

        sem = asyncio.Semaphore(self.concurrency)

        async def fetch_page(offset: int) -> list[dict[str, object]]:
            async with sem:
                page_params = dict(params)
                page_params["sysparm_offset"] = str(offset)
                url = f"{self.instance_url}/api/now/table/{table}"
                data = await self._request("GET", url, params=page_params)
                raw = data.get("result") if isinstance(data, dict) else None
                if raw is None or not isinstance(raw, list):
                    return []
                return cast(list[dict[str, object]], raw)

        tasks = [asyncio.create_task(fetch_page(i * self.page_size)) for i in range(page_count)]
        for fut in asyncio.as_completed(tasks):
            records = await fut
            for rec in records:
                yield rec

    async def aget_record(self, table: str, sys_id: str) -> dict[str, object]:
        """Fetch a single record by sys_id."""
        if not sys_id or not sys_id.strip():
            raise SnowConnectionError("sys_id must not be empty for single-record lookup.")
        url = f"{self.instance_url}/api/now/table/{table}/{sys_id}"
        data = await self._request("GET", url)
        if "result" not in data:
            raise SnowConnectionError(
                f"Unexpected API response for {table}/{sys_id}: missing 'result' key.",
                detail=str(data),
            )
        return cast(dict[str, object], data["result"])

    async def aget_attachment(self, sys_id: str) -> bytes:
        """Download a sys_attachment binary asynchronously.

        Args:
            sys_id: The attachment ``sys_id``.

        Returns:
            Raw file bytes.

        Raises:
            SnowConnectionError: On any non-2xx response or network failure.
        """
        if not sys_id or not sys_id.strip():
            raise SnowConnectionError("sys_id must not be empty for attachment download.")

        await self._ensure_session()
        await self._ensure_token()

        headers: dict[str, str] = {"Accept": "*/*"}
        if self.auth_type in ("oauth", "client_credentials", "bearer"):
            headers["Authorization"] = f"Bearer {self._access_token}"

        url = f"{self.instance_url}/api/now/attachment/{sys_id}/file"
        attempt = 0
        backoff = self.retry_backoff
        last_status: int | None = None
        last_body = ""

        while True:
            try:
                assert self._session is not None
                async with self._session.get(
                    url,
                    headers=headers,
                    proxy=self._proxy,
                ) as resp:
                    last_status = resp.status
                    if resp.status in _RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                        await asyncio.sleep(backoff)
                        attempt += 1
                        backoff *= 2
                        continue
                    if resp.status >= 400:
                        last_body = await resp.text()
                        raise SnowConnectionError(
                            f"Attachment {sys_id} returned {resp.status}",
                            status_code=resp.status,
                            detail=last_body,
                        )
                    return await resp.read()
            except aiohttp.ClientError as exc:
                if attempt < self.max_retries:
                    await asyncio.sleep(backoff)
                    attempt += 1
                    backoff *= 2
                    continue
                raise SnowConnectionError(
                    f"Network error downloading attachment {sys_id}: {exc}",
                    status_code=last_status,
                    detail=last_body,
                ) from exc
