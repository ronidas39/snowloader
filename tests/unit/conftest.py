"""Make the HTTP mocks behave the way ServiceNow actually behaves.

A sweep ends when the instance returns an empty page. It cannot end on a short
page, because ServiceNow applies read ACLs after selecting a page, so a request
for 100 rows can come back with 40 while thousands remain. Measured on a
developer instance, sys_db_object returned 769 rows at page size 100 and 969 at
page size 500 against a reported 6,456, and walking to an empty page returned
6,419.

The mocks in this suite were written against the old rule, so most register one
short page and expect the read to stop there. Left alone, ``responses`` replays
that last registration forever and every one of them spins.

Rather than edit a hundred and thirty eight tests, the registry below returns
an empty result once a test's registrations are exhausted, which is exactly
what the instance does past the end of a table. Every assertion in those tests
is untouched; only the fixture becomes realistic.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from responses import registries

if TYPE_CHECKING:  # pragma: no cover
    from requests import PreparedRequest


_TABLE_PATH = "/api/now/table/"


def _is_a_sweep_continuation(url: str) -> bool:
    """Is this request asking for a page after the first.

    Offset paging says so with sysparm_offset. Keyset paging carries no
    offset at all and instead puts the cursor in the query, so the marker
    there is the sys_id comparison the cursor is built from.
    """
    query = parse_qs(urlparse(url).query)
    offset = query.get("sysparm_offset", ["0"])[0]
    try:
        if int(offset) > 0:
            return True
    except ValueError:
        pass
    return any("sys_id>" in v for v in query.get("sysparm_query", []))


def _looks_like_a_result_page(body: Any) -> bool:
    """Is this the ordinary {"result": [...]} shape a table read returns."""
    if body is None:
        return False
    if isinstance(body, bytes):
        try:
            body = body.decode()
        except UnicodeDecodeError:
            return False
    if not isinstance(body, str):
        return False
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return False
    return isinstance(parsed, dict) and isinstance(parsed.get("result"), list)


class _EndsLikeServiceNow(registries.FirstMatchRegistry):
    """A registry whose table reads run out into an empty page.

    Only Table API reads get the synthetic ending. A missing mock for a stats
    call, an attachment download or an OAuth token exchange still fails loudly,
    because a test that forgot one of those has a real gap in it.
    """

    def find(self, request: PreparedRequest) -> tuple[responses.BaseResponse | None, list[str]]:
        found, reasons = super().find(request)
        url = request.url or ""
        if _TABLE_PATH not in url:
            return found, reasons
        # Only a continuation of a sweep gets the synthetic ending. The first
        # page of any read, and every single-record lookup, is left alone.
        # Without this the per-CI relationship fetches in the CMDB tests stop
        # resolving, because those rely on one registration serving many
        # separate lookups rather than on pagination.
        if not _is_a_sweep_continuation(url):
            return found, reasons
        # An exhausted registry does not return None, it replays the last
        # response. That replay is what spins a sweep forever, so it is the
        # signal to hand back the empty page the instance would send.
        if found is not None and found.call_count == 0:
            return found, reasons
        # A replayed failure must keep failing. Retry and the skip policy are
        # both tested by registering one bad page and letting it repeat, and
        # turning that into an empty success would quietly delete those tests.
        if found is not None and found.status >= 400:
            return found, reasons
        # A replayed malformed body must stay malformed. Several tests hand
        # back null, a bare list or a string to prove the read refuses them
        # after retrying, and substituting a clean empty page would delete
        # exactly the behaviour under test.
        body = getattr(found, "body", None)
        if found is not None and not _looks_like_a_result_page(body):
            return found, reasons
        return (
            responses.Response(
                method=responses.GET,
                url=request.url,
                json={"result": []},
                status=200,
            ),
            reasons,
        )


@pytest.fixture(autouse=True)
def _servicenow_shaped_mocks(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Any:
    """Give every mock in this suite the registry above.

    Two mechanisms are in use across these tests. Newer ones build their own
    ``responses.RequestsMock``; older ones use the ``@responses.activate``
    decorator, which runs against a module level singleton created at import
    time and so is untouched by patching the class.
    """
    if request.node.get_closest_marker("replaying_mocks"):
        # The test deliberately relies on one registration serving every
        # offset. The threaded paginator takes its page count from the record
        # count rather than from an empty page, so it never needs the ending
        # this fixture supplies, and supplying it would blank its later pages.
        yield None
        return

    original = responses.RequestsMock.__init__

    def patched(self: responses.RequestsMock, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("registry", _EndsLikeServiceNow)
        original(self, *args, **kwargs)

    monkeypatch.setattr(responses.RequestsMock, "__init__", patched)

    # The singleton behind @responses.activate. Its registry is swapped for
    # the run and restored afterwards.
    singleton = responses.mock
    previous = singleton._registry
    singleton._set_registry(_EndsLikeServiceNow)
    try:
        yield None
    finally:
        singleton._registry = previous
