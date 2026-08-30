"""The async path should trust the same certificates the sync path does.

``requests`` bundles certifi, so the sync connection verifies a ServiceNow
certificate anywhere. ``aiohttp`` uses the operating system store instead, and
a stock python.org build on macOS has an empty one, so the identical
credentials against the identical instance failed with CERTIFICATE_VERIFY_FAILED
on the async path alone.

Making the two agree is not a security relaxation. It is the same trust store,
reached the same way, and ``verify_ssl=False`` still means what it always did.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import ssl

import pytest

pytest.importorskip("aiohttp")

from snowloader.async_connection import AsyncSnowConnection  # noqa: E402

BASE_URL = "https://test.service-now.com"


def _conn(**kwargs: object) -> AsyncSnowConnection:
    return AsyncSnowConnection(instance_url=BASE_URL, username="admin", password="secret", **kwargs)


def test_verification_uses_a_real_trust_store_by_default() -> None:
    """True on its own hands aiohttp the system store, which is empty on a
    stock macOS python.org build."""
    conn = _conn()
    assert isinstance(conn._verify_ssl, ssl.SSLContext)


def test_the_default_context_actually_verifies() -> None:
    conn = _conn()
    context = conn._verify_ssl
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_the_default_context_carries_certificates() -> None:
    conn = _conn()
    context = conn._verify_ssl
    assert isinstance(context, ssl.SSLContext)
    assert context.cert_store_stats()["x509_ca"] > 0


def test_verification_can_still_be_turned_off() -> None:
    assert _conn(verify_ssl=False)._verify_ssl is False


def test_a_caller_supplied_context_is_left_alone() -> None:
    mine = ssl.create_default_context()
    assert _conn(verify_ssl=mine)._verify_ssl is mine
