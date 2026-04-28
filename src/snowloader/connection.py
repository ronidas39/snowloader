"""Core ServiceNow API connection handler for snowloader.

This module provides SnowConnection, the single point of contact between
snowloader and the ServiceNow Table API. Every loader in the library routes
its HTTP traffic through this class, which handles:

    - Authentication (Basic, OAuth 2.0 password/client-credentials, Bearer token)
    - Pagination (sysparm_limit / sysparm_offset with stable ordering)
    - Retry logic (exponential backoff for 429, 503, and transient errors)
    - Rate limiting (configurable delay between requests)
    - Input validation (URL format, page_size bounds, table names)
    - Session lifecycle (context manager support for clean shutdown)
    - Thread-safe HTTP via a request lock
    - Proxy and custom CA certificate support

Author: Roni Das
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Generator
from datetime import datetime
from types import TracebackType
from typing import Any, cast

import requests

logger = logging.getLogger(__name__)

# Retry defaults
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BACKOFF = 1.0  # seconds, doubles each attempt
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
_MAX_PAGE_SIZE = 10000
_MIN_PAGE_SIZE = 1

# Regex for validating ServiceNow instance URLs
_INSTANCE_URL_PATTERN = re.compile(r"^https?://[a-zA-Z0-9][-a-zA-Z0-9.]+\.[a-zA-Z]{2,}")


class SnowConnectionError(Exception):
    """Raised when something goes wrong talking to the ServiceNow API.

    Attributes:
        status_code: HTTP status code if the error came from an API response.
            None for network-level failures (timeout, DNS, connection refused).
        detail: Human-readable error detail extracted from the response body
            or the underlying exception message.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class SnowConnection:
    """Manages a session against one ServiceNow instance.

    Supports four authentication modes (checked in priority order):

        1. **Bearer token** - pass a pre-obtained token directly via
           ``token``. No user credentials needed. Useful when auth is
           handled outside the library (SSO, external token service).
        2. **OAuth 2.0 Client Credentials** - pass ``client_id`` and
           ``client_secret`` without ``username``/``password``. Best for
           server-to-server integrations with no human user involved.
        3. **OAuth 2.0 Password Grant** - pass all four: ``client_id``,
           ``client_secret``, ``username``, ``password``. Token is acquired
           lazily on first request and refreshed on 401.
        4. **Basic Auth** - pass ``username`` and ``password`` only.
           Simplest; fine for development, not recommended for production.

    Can be used as a context manager for clean session shutdown::

        with SnowConnection(...) as conn:
            loader = IncidentLoader(connection=conn)
            docs = loader.load()

    Args:
        instance_url: Full URL of the ServiceNow instance, e.g.
            ``"https://mycompany.service-now.com"``. Trailing slashes
            are stripped automatically.
        username: ServiceNow user account for authentication.
        password: Password for the user account.
        client_id: OAuth client ID. Enables OAuth when combined with
            ``client_secret``.
        client_secret: OAuth client secret.
        token: Pre-obtained Bearer token. When provided, all other
            credentials are ignored.
        page_size: Records per API call during pagination (1-10 000).
            Defaults to 100.
        timeout: HTTP request timeout in seconds. Defaults to 60.
        max_retries: Retry attempts for transient failures (429, 502,
            503, 504). Defaults to 3.
        retry_backoff: Base delay (seconds) between retries; doubles
            on each attempt. Defaults to 1.0.
        request_delay: Minimum seconds between consecutive API requests.
            Helps avoid rate limiting. Defaults to 0 (no delay).
        display_value: Controls ``sysparm_display_value`` parameter.
            ``"true"`` (default) returns human-readable labels for
            reference fields. ``"false"`` returns raw values. ``"all"``
            returns both ``{display_value, value}`` dicts.
        proxy: Optional proxy URL, e.g. ``"http://proxy:8080"``.
            Applied to all HTTP(S) requests.
        verify: SSL verification. ``True`` (default) uses system CA
            bundle. Pass a path string to a CA bundle file for custom
            certificates. ``False`` disables verification (not
            recommended for production).

    Raises:
        SnowConnectionError: If credentials are missing or invalid,
            or if instance_url is malformed.

    Example:
        >>> conn = SnowConnection(
        ...     instance_url="https://mycompany.service-now.com",
        ...     username="api_user",
        ...     password="api_pass",
        ... )
        >>> for record in conn.get_records("incident", query="active=true"):
        ...     print(record["number"])
    """

    def __init__(
        self,
        instance_url: str,
        username: str | None = None,
        password: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        token: str | None = None,
        page_size: int = 100,
        timeout: int = 60,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_backoff: float = _DEFAULT_RETRY_BACKOFF,
        request_delay: float = 0.0,
        display_value: str = "true",
        proxy: str | None = None,
        verify: bool | str = True,
    ) -> None:
        # -- Validate inputs --
        if not instance_url or not instance_url.strip():
            raise SnowConnectionError(
                "instance_url must not be empty.",
                detail="Provide a URL like https://mycompany.service-now.com",
            )

        cleaned_url = instance_url.rstrip("/")
        if not _INSTANCE_URL_PATTERN.match(cleaned_url):
            raise SnowConnectionError(
                f"instance_url '{cleaned_url}' is not a valid HTTP(S) URL.",
                detail="URL must start with http:// or https:// followed by "
                "a valid domain (e.g. https://mycompany.service-now.com).",
            )

        if not _MIN_PAGE_SIZE <= page_size <= _MAX_PAGE_SIZE:
            raise SnowConnectionError(
                f"page_size must be between {_MIN_PAGE_SIZE} and {_MAX_PAGE_SIZE}, "
                f"got {page_size}.",
            )

        if timeout <= 0:
            raise SnowConnectionError(
                f"timeout must be positive, got {timeout}.",
            )

        if display_value not in ("true", "false", "all"):
            raise SnowConnectionError(
                f"display_value must be 'true', 'false', or 'all', got '{display_value}'.",
            )

        self.instance_url = cleaned_url
        self.page_size = page_size
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.request_delay = request_delay
        self.display_value = display_value
        self._last_request_time: float = 0.0
        self._request_lock = threading.Lock()

        # -- Session setup --
        self._session = requests.Session()
        self._session.verify = verify

        if proxy:
            self._session.proxies = {"http": proxy, "https": proxy}
            logger.info("Using proxy %s for %s", proxy, self.instance_url)

        # -- Auth setup (priority: token > client_credentials > password > basic) --
        if token:
            self.auth_type = "bearer"
            self._access_token: str | None = token
            logger.info("Configured bearer token auth for %s", self.instance_url)
        elif client_id and client_secret and not username:
            self.auth_type = "client_credentials"
            self._client_id = client_id
            self._client_secret = client_secret
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
            self._session.auth = (username, password)
            logger.info("Configured basic auth for %s", self.instance_url)
        else:
            raise SnowConnectionError(
                "SnowConnection requires credentials. Provide one of:\n"
                "  - token (pre-obtained bearer token)\n"
                "  - client_id + client_secret (OAuth client credentials)\n"
                "  - client_id + client_secret + username + password (OAuth password grant)\n"
                "  - username + password (basic auth)",
                detail="Check your credentials and try again.",
            )

    # -- Context manager --

    def __enter__(self) -> SnowConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP session and release resources.

        Safe to call multiple times. After closing, further API calls
        will raise an error from the requests library.
        """
        self._session.close()
        logger.debug("Session closed for %s", self.instance_url)

    # -- Public API --

    def get_records(
        self,
        table: str,
        query: str | None = None,
        fields: list[str] | None = None,
        since: datetime | None = None,
    ) -> Generator[dict[str, object], None, None]:
        """Fetch records from a ServiceNow table with automatic pagination.

        Yields one record dict at a time so callers can process large
        result sets without holding everything in memory. Pagination
        continues until the API returns fewer records than page_size,
        which signals we have reached the last page.

        Args:
            table: ServiceNow table name, e.g. "incident" or "cmdb_ci_server".
            query: Optional encoded query string, e.g. "active=true^priority=1".
                An ORDERBYsys_created_on suffix is appended automatically.
            fields: Optional list of field names to include in the response.
                When omitted, ServiceNow returns all fields on the table.
            since: Optional datetime for delta/incremental sync. When set,
                only records updated after this timestamp are returned.

        Yields:
            Individual record dicts straight from the ServiceNow response.

        Raises:
            SnowConnectionError: On any non-2xx response from the API.
        """
        if not table or not table.strip():
            raise SnowConnectionError(
                "table name must not be empty.",
                detail="Provide a ServiceNow table name like 'incident'.",
            )

        params = self._build_query_params(query=query, fields=fields, since=since)
        offset = 0
        total_yielded = 0

        logger.info(
            "Starting paginated fetch from '%s' (page_size=%d)",
            table,
            self.page_size,
        )

        while True:
            params["sysparm_offset"] = str(offset)
            url = f"{self.instance_url}/api/now/table/{table}"

            response_data = self._request("GET", url, params=params)
            raw_result = response_data.get("result")

            if raw_result is None:
                logger.warning(
                    "API response for '%s' had no 'result' key, treating as empty.",
                    table,
                )
                break

            records: list[dict[str, object]] = cast(list[dict[str, object]], raw_result)

            yield from records
            total_yielded += len(records)

            if len(records) < self.page_size:
                break

            offset += self.page_size
            logger.debug(
                "Fetched page (offset=%d, records=%d, total_so_far=%d)",
                offset,
                len(records),
                total_yielded,
            )

        logger.info("Completed fetch from '%s': %d records total.", table, total_yielded)

    def get_attachment(self, sys_id: str) -> bytes:
        """Download the binary content of one ``sys_attachment`` record.

        Hits the ``/api/now/attachment/<sys_id>/file`` endpoint and returns the
        raw bytes. Honors the connection's auth, retries, and timeout settings.

        Args:
            sys_id: The ``sys_id`` of the attachment record.

        Returns:
            Raw bytes of the attachment file.

        Raises:
            SnowConnectionError: On any non-2xx response or network failure.
        """
        if not sys_id or not sys_id.strip():
            raise SnowConnectionError(
                "sys_id must not be empty for attachment download.",
            )

        self._ensure_oauth_token()
        self._throttle()

        url = f"{self.instance_url}/api/now/attachment/{sys_id}/file"
        headers: dict[str, str] = {"Accept": "*/*"}
        if self.auth_type in ("oauth", "client_credentials", "bearer") and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        last_error: SnowConnectionError | None = None
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                backoff = self.retry_backoff * (2 ** (attempt - 1))
                time.sleep(backoff)

            try:
                with self._request_lock:
                    resp = self._session.get(
                        url,
                        headers=headers,
                        timeout=self.timeout,
                    )
                self._last_request_time = time.monotonic()
            except requests.RequestException as exc:
                last_error = SnowConnectionError(
                    f"Network error downloading attachment {sys_id}: {exc}",
                )
                continue

            if resp.ok:
                return resp.content

            if resp.status_code in _RETRYABLE_STATUS_CODES:
                detail = self._extract_error_detail(resp)
                last_error = SnowConnectionError(
                    f"Attachment {sys_id} returned {resp.status_code}: {detail}",
                    status_code=resp.status_code,
                    detail=detail,
                )
                continue

            detail = self._extract_error_detail(resp)
            raise SnowConnectionError(
                f"Attachment {sys_id} returned {resp.status_code}: {detail}",
                status_code=resp.status_code,
                detail=detail,
            )

        if last_error:
            raise last_error
        raise SnowConnectionError(  # pragma: no cover
            f"Unexpected retry loop exit downloading attachment {sys_id}",
        )

    def get_record(self, table: str, sys_id: str) -> dict[str, object]:
        """Fetch a single record by its sys_id.

        Args:
            table: ServiceNow table name.
            sys_id: The unique sys_id of the record to fetch.

        Returns:
            The record dict from the API response.

        Raises:
            SnowConnectionError: If the record does not exist or the
                API returns an error status.
        """
        if not sys_id or not sys_id.strip():
            raise SnowConnectionError(
                "sys_id must not be empty for single-record lookup.",
            )

        url = f"{self.instance_url}/api/now/table/{table}/{sys_id}"
        response_data = self._request("GET", url)

        if "result" not in response_data:
            raise SnowConnectionError(
                f"Unexpected API response for {table}/{sys_id}: missing 'result' key.",
                detail=str(response_data),
            )

        return cast(dict[str, object], response_data["result"])

    # -- Internal helpers --

    def _build_query_params(
        self,
        query: str | None = None,
        fields: list[str] | None = None,
        since: datetime | None = None,
    ) -> dict[str, str]:
        """Assemble the sysparm_* query parameters for a table request.

        Args:
            query: User-supplied encoded query, or None.
            fields: List of field names to request, or None for all.
            since: Delta sync cutoff timestamp, or None.

        Returns:
            Dict of query parameter key-value pairs.
        """
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

    def _acquire_oauth_token(self) -> str:
        """Acquire an OAuth 2.0 access token.

        Supports both password grant (when username/password are set)
        and client credentials grant (when only client_id/secret are set).

        Returns:
            The access token string.

        Raises:
            SnowConnectionError: If the token request fails.
        """
        token_url = f"{self.instance_url}/oauth_token.do"

        if self.auth_type == "client_credentials":
            grant_data: dict[str, str] = {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
            logger.debug("Requesting OAuth token (client_credentials) from %s", token_url)
        else:
            grant_data = {
                "grant_type": "password",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "username": self._username,
                "password": self._password,
            }
            logger.debug("Requesting OAuth token (password grant) from %s", token_url)

        try:
            resp = self._session.post(
                token_url,
                data=grant_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SnowConnectionError(
                f"OAuth token request failed: {exc}",
                detail="Check your network connection and instance URL.",
            ) from exc

        if not resp.ok:
            detail = resp.text if resp.text else "No response body"
            raise SnowConnectionError(
                f"OAuth token request returned {resp.status_code}.",
                status_code=resp.status_code,
                detail=f"Verify your OAuth credentials are correct. Response: {detail}",
            )

        try:
            token_data = resp.json()
        except ValueError as exc:
            raise SnowConnectionError(
                "OAuth token response was not valid JSON.",
                detail=resp.text,
            ) from exc

        access_token = token_data.get("access_token")
        if not access_token:
            raise SnowConnectionError(
                "OAuth response did not contain an access_token.",
                detail=f"Response keys: {list(token_data.keys())}",
            )

        logger.info("OAuth token acquired successfully for %s", self.instance_url)
        return str(access_token)

    def _ensure_oauth_token(self) -> None:
        """Ensure we have a valid OAuth token, acquiring one if needed."""
        if self.auth_type not in ("oauth", "client_credentials"):
            return
        if self._access_token is None:
            self._access_token = self._acquire_oauth_token()

    def _throttle(self) -> None:
        """Enforce minimum delay between consecutive API requests."""
        if self.request_delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.request_delay:
            sleep_time = self.request_delay - elapsed
            logger.debug("Rate limiting: sleeping %.3fs", sleep_time)
            time.sleep(sleep_time)

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send an HTTP request with retry logic and error handling.

        Thread-safe: uses a lock around the HTTP call so concurrent
        threads (e.g. CMDB relationship fetching) do not corrupt the
        shared requests.Session state.

        Retries transient failures (429, 502, 503, 504) with exponential
        backoff. Respects Retry-After headers from 429 responses. Raises
        SnowConnectionError on permanent failures with structured details.

        Args:
            method: HTTP method, typically "GET".
            url: Full URL including the instance base and API path.
            params: Optional query parameters.

        Returns:
            Parsed JSON response body as a dict.

        Raises:
            SnowConnectionError: On permanent HTTP errors or exhausted retries.
        """
        self._ensure_oauth_token()
        self._throttle()

        headers: dict[str, str] = {"Accept": "application/json"}
        if self.auth_type in ("oauth", "client_credentials", "bearer") and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        last_error: SnowConnectionError | None = None

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                backoff = self.retry_backoff * (2 ** (attempt - 1))
                logger.warning(
                    "Retry %d/%d for %s %s (waiting %.1fs)",
                    attempt,
                    self.max_retries,
                    method,
                    url,
                    backoff,
                )
                time.sleep(backoff)

            logger.debug("%s %s params=%s (attempt %d)", method, url, params, attempt)

            try:
                with self._request_lock:
                    resp = self._session.request(
                        method=method,
                        url=url,
                        params=params,
                        headers=headers,
                        timeout=self.timeout,
                    )
                self._last_request_time = time.monotonic()
            except requests.ConnectionError as exc:
                last_error = SnowConnectionError(
                    f"Connection failed to {self.instance_url}: {exc}",
                    detail="Check your network connection and instance URL. "
                    "The instance may be hibernating (dev instances sleep "
                    "after inactivity - wake it by visiting the URL in a "
                    "browser).",
                )
                continue
            except requests.Timeout:
                last_error = SnowConnectionError(
                    f"Request timed out after {self.timeout}s for {method} {url}",
                    detail="The instance may be under heavy load. Try "
                    "increasing the timeout parameter or reducing page_size.",
                )
                continue
            except requests.RequestException as exc:
                raise SnowConnectionError(
                    f"Unexpected request error: {type(exc).__name__}: {exc}",
                    detail="This is likely a configuration or network issue.",
                ) from exc

            # -- Handle response --
            if resp.ok:
                try:
                    result: dict[str, Any] = resp.json()
                    return result
                except ValueError as exc:
                    raise SnowConnectionError(
                        f"API returned non-JSON response for {method} {url}",
                        status_code=resp.status_code,
                        detail=f"Content-Type: "
                        f"{resp.headers.get('Content-Type')}. "
                        f"Body: {resp.text}",
                    ) from exc

            # -- Retryable errors --
            if resp.status_code in _RETRYABLE_STATUS_CODES:
                retry_after = resp.headers.get("Retry-After")
                if resp.status_code == 429 and retry_after:
                    try:
                        wait = float(retry_after)
                        logger.warning(
                            "Rate limited (429). Server says wait %.1fs.",
                            wait,
                        )
                        time.sleep(wait)
                    except ValueError:
                        pass  # Non-numeric Retry-After, use backoff

                detail = self._extract_error_detail(resp)
                last_error = SnowConnectionError(
                    f"ServiceNow API returned {resp.status_code} for {method} {url}: {detail}",
                    status_code=resp.status_code,
                    detail=detail,
                )
                continue

            # -- OAuth token expired: re-acquire and retry once --
            if (
                resp.status_code == 401
                and self.auth_type in ("oauth", "client_credentials")
                and attempt == 0
            ):
                logger.warning("Got 401, attempting OAuth token refresh.")
                try:
                    self._access_token = self._acquire_oauth_token()
                    headers["Authorization"] = f"Bearer {self._access_token}"
                    continue
                except SnowConnectionError:
                    logger.error("OAuth token refresh failed.")

            # -- Permanent error --
            detail = self._extract_error_detail(resp)
            raise SnowConnectionError(
                f"ServiceNow API returned {resp.status_code} for {method} {url}: {detail}",
                status_code=resp.status_code,
                detail=detail,
            )

        # All retries exhausted
        if last_error:
            raise SnowConnectionError(
                f"All {self.max_retries} retries exhausted for "
                f"{method} {url}. Last error: {last_error}",
                status_code=last_error.status_code,
                detail=last_error.detail,
            )

        raise SnowConnectionError(  # pragma: no cover
            f"Unexpected retry loop exit for {method} {url}",
        )

    @staticmethod
    def _extract_error_detail(resp: requests.Response) -> str:
        """Pull a human-readable error message from an API error response.

        Args:
            resp: The HTTP response object.

        Returns:
            A descriptive error string.
        """
        try:
            body = resp.json()
            if isinstance(body, dict) and "error" in body:
                error_obj = body["error"]
                if isinstance(error_obj, dict):
                    msg = error_obj.get("message", "")
                    detail = error_obj.get("detail", "")
                    if msg and detail:
                        return f"{msg} - {detail}"
                    return str(msg or detail or body)
                return str(error_obj)
        except (ValueError, TypeError):
            pass
        # Fallback to raw text
        if resp.text:
            return resp.text
        return f"HTTP {resp.status_code} (no response body)"
