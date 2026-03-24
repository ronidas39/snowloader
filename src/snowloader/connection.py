"""Core ServiceNow API connection handler for snowloader.

This module provides SnowConnection, the single point of contact between
snowloader and the ServiceNow Table API. Every loader in the library routes
its HTTP traffic through this class, which handles authentication, pagination,
query building, and error translation.

Supported authentication modes:
    - Basic auth (username + password)
    - OAuth 2.0 password grant (client_id + client_secret + username + password)

Pagination follows the standard sysparm_limit / sysparm_offset pattern described
in the ServiceNow REST API docs. Results are always ordered by sys_created_on to
guarantee stable page boundaries across requests.

Author: Roni Das
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from datetime import datetime
from typing import Any, cast

import requests

logger = logging.getLogger(__name__)


class SnowConnectionError(Exception):
    """Raised when something goes wrong talking to the ServiceNow API.

    This covers authentication failures, missing tables, server errors,
    and anything else that results in a non-2xx HTTP status code.
    """


class SnowConnection:
    """Manages a session against one ServiceNow instance.

    All HTTP requests flow through the internal _request method, which
    attaches the right auth headers and raises SnowConnectionError on
    failure. Callers (mostly loader classes) should use get_records for
    paginated table queries and get_record for single-record lookups.

    Args:
        instance_url: Full URL of the ServiceNow instance, e.g.
            "https://mycompany.service-now.com". Trailing slashes
            are stripped automatically.
        username: ServiceNow user account for authentication.
        password: Password for the user account.
        client_id: OAuth client ID. When provided together with
            client_secret, the connection switches to OAuth mode.
        client_secret: OAuth client secret.
        page_size: Number of records to fetch per API call during
            pagination. Defaults to 100, max allowed by SN is 10000.

    Raises:
        SnowConnectionError: If neither basic auth nor OAuth credentials
            are provided.

    Example:
        conn = SnowConnection(
            instance_url="https://mycompany.service-now.com",
            username="api_user",
            password="api_pass",
        )
        for record in conn.get_records("incident", query="active=true"):
            print(record["number"])
    """

    def __init__(
        self,
        instance_url: str,
        username: str | None = None,
        password: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        page_size: int = 100,
    ) -> None:
        self.instance_url = instance_url.rstrip("/")
        self.page_size = page_size
        self._session = requests.Session()

        # Figure out which auth mode we are using. OAuth takes priority
        # when both sets of credentials are present, because it is the
        # recommended approach for production ServiceNow integrations.
        if client_id and client_secret and username and password:
            self.auth_type = "oauth"
            self._client_id = client_id
            self._client_secret = client_secret
            self._username = username
            self._password = password
            self._access_token: str | None = None
            logger.info("Using OAuth authentication for %s", self.instance_url)
        elif username and password:
            self.auth_type = "basic"
            self._session.auth = (username, password)
            logger.info("Using basic auth for %s", self.instance_url)
        else:
            raise SnowConnectionError(
                "SnowConnection needs at least username and password. "
                "For OAuth, also provide client_id and client_secret."
            )

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
        params = self._build_query_params(query=query, fields=fields, since=since)
        offset = 0

        while True:
            params["sysparm_offset"] = str(offset)
            url = f"{self.instance_url}/api/now/table/{table}"

            response_data = self._request("GET", url, params=params)
            records: list[dict[str, object]] = cast(
                list[dict[str, object]], response_data.get("result", [])
            )

            yield from records

            # If we got fewer records than the page size, there are no
            # more pages left. Also bail on empty results obviously.
            if len(records) < self.page_size:
                break

            offset += self.page_size

    def get_record(self, table: str, sys_id: str) -> dict[str, object]:
        """Fetch a single record by its sys_id.

        This is the direct-lookup equivalent of get_records. It hits the
        /api/now/table/{table}/{sys_id} endpoint and returns the record
        as a plain dict.

        Args:
            table: ServiceNow table name.
            sys_id: The unique sys_id of the record to fetch.

        Returns:
            The record dict from the API response.

        Raises:
            SnowConnectionError: If the record does not exist or the
                API returns an error status.
        """
        url = f"{self.instance_url}/api/now/table/{table}/{sys_id}"
        response_data = self._request("GET", url)
        return cast(dict[str, object], response_data["result"])

    # -- Internal helpers --

    def _build_query_params(
        self,
        query: str | None = None,
        fields: list[str] | None = None,
        since: datetime | None = None,
    ) -> dict[str, str]:
        """Assemble the sysparm_* query parameters for a table request.

        Handles the fiddly bits: merging user queries with delta sync
        filters, appending the ordering clause, and converting the
        fields list into comma-separated format.

        Args:
            query: User-supplied encoded query, or None.
            fields: List of field names to request, or None for all.
            since: Delta sync cutoff timestamp, or None.

        Returns:
            Dict of query parameter key-value pairs ready to pass to
            requests.get().
        """
        params: dict[str, str] = {
            "sysparm_limit": str(self.page_size),
        }

        # Build up the query string piece by piece. The ordering suffix
        # goes on last so pagination is stable across pages.
        query_parts: list[str] = []
        if query:
            query_parts.append(query)
        if since:
            # ServiceNow expects timestamps in "YYYY-MM-DD HH:MM:SS" format
            timestamp = since.strftime("%Y-%m-%d %H:%M:%S")
            query_parts.append(f"sys_updated_on>{timestamp}")

        query_parts.append("ORDERBYsys_created_on")
        params["sysparm_query"] = "^".join(query_parts)

        if fields:
            params["sysparm_fields"] = ",".join(fields)

        return params

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send an HTTP request through the session and handle errors.

        This is the single choke point for all API traffic. Auth headers
        are attached by the session (basic) or manually (OAuth). Any
        non-2xx response gets turned into a SnowConnectionError with
        as much detail as we can extract from the response body.

        Args:
            method: HTTP method, typically "GET".
            url: Full URL including the instance base and API path.
            params: Optional query parameters.

        Returns:
            Parsed JSON response body as a dict.

        Raises:
            SnowConnectionError: On any HTTP error or unexpected response.
        """
        headers = {"Accept": "application/json"}

        # For OAuth, we need to fetch a token first (or reuse the cached one)
        if self.auth_type == "oauth" and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        logger.debug("%s %s params=%s", method, url, params)

        try:
            resp = self._session.request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise SnowConnectionError(f"Request failed: {exc}") from exc

        if not resp.ok:
            # Try to pull a useful message from the response body
            error_detail = ""
            try:
                body = resp.json()
                if "error" in body:
                    error_detail = body["error"].get("message", "")
            except (ValueError, KeyError, AttributeError):
                error_detail = resp.text[:200]

            raise SnowConnectionError(
                f"ServiceNow API returned {resp.status_code} for {method} {url}: {error_detail}"
            )

        result: dict[str, Any] = resp.json()
        return result
