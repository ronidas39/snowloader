"""End-to-end smoke tests for the full snowloader pipeline.

These tests wire the entire stack together — SnowConnection through every
loader through both framework adapters — against a fake ServiceNow API built
with the ``responses`` library. The mock data is realistic and exercises every
code path:

    - Pagination (multiple pages of results)
    - All 6 loaders with table-specific formatting
    - Display-value reference fields (dict with display_value/value)
    - Conditional field rendering (empty fields omitted from text)
    - HTML cleaning in KB articles
    - Journal entries (work notes + comments from sys_journal_field)
    - Delta sync (load_since filters by sys_updated_on)
    - CMDB relationship traversal (outbound + inbound)
    - Boolean normalization (known_error, active)
    - LangChain adapter (BaseLoader → Document with page_content/metadata)
    - LlamaIndex adapter (BaseReader → Document with text/metadata/excluded keys)
    - Source URL construction per loader
    - Kwargs passthrough to adapters (ci_class, include_relationships, etc.)

Author: Roni Das
"""

from __future__ import annotations

from datetime import datetime, timezone

import responses

from snowloader import (
    CatalogLoader,
    ChangeLoader,
    CMDBLoader,
    IncidentLoader,
    KnowledgeBaseLoader,
    ProblemLoader,
    SnowConnection,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

BASE_URL = "https://smoke.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"


def _conn() -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="u", password="p")


# ---------------------------------------------------------------------------
# Realistic mock data per table
# ---------------------------------------------------------------------------

INCIDENTS = [
    {
        "sys_id": "inc1",
        "number": "INC0010001",
        "short_description": "Email server down",
        "description": "Exchange cluster is unreachable since 09:00.",
        "state": {"display_value": "In Progress", "value": "2"},
        "priority": {"display_value": "1 - Critical", "value": "1"},
        "category": "network",
        "subcategory": "email",
        "assigned_to": {"display_value": "Alice", "value": "uid-alice"},
        "assignment_group": {"display_value": "NOC", "value": "grp-noc"},
        "cmdb_ci": {"display_value": "mail-prod-01", "value": "ci-mail"},
        "opened_at": "2024-06-01 09:00:00",
        "closed_at": "",
        "resolved_at": "",
        "close_notes": "",
        "sys_created_on": "2024-06-01 09:00:00",
        "sys_updated_on": "2024-06-01 09:05:00",
    },
    {
        "sys_id": "inc2",
        "number": "INC0010002",
        "short_description": "VPN timeout",
        "description": "",
        "state": {"display_value": "New", "value": "1"},
        "priority": {"display_value": "3 - Moderate", "value": "3"},
        "category": "network",
        "subcategory": "",
        "assigned_to": "",
        "assignment_group": "",
        "cmdb_ci": "",
        "opened_at": "2024-06-02 10:00:00",
        "closed_at": "",
        "resolved_at": "",
        "close_notes": "",
        "sys_created_on": "2024-06-02 10:00:00",
        "sys_updated_on": "2024-06-02 10:00:00",
    },
]

KB_ARTICLES = [
    {
        "sys_id": "kb1",
        "number": "KB0000101",
        "short_description": "How to reset your VPN password",
        "text": "<p>Go to <b>Settings &gt; VPN</b>.</p><br/><p>Click <i>Reset</i>.</p>",
        "wiki": "",
        "topic": "VPN",
        "category": "self-service",
        "author": {"display_value": "Doc Team", "value": "uid-doc"},
        "kb_knowledge_base": {"display_value": "IT KB", "value": "kb-it"},
        "workflow_state": "published",
        "sys_created_on": "2024-01-15 08:00:00",
        "sys_updated_on": "2024-03-10 14:00:00",
    },
]

CMDB_CIS = [
    {
        "sys_id": "ci1",
        "name": "web-prod-01",
        "sys_class_name": "cmdb_ci_server",
        "short_description": "Production web server",
        "operational_status": {"display_value": "Operational", "value": "1"},
        "environment": "production",
        "ip_address": "10.0.1.10",
        "fqdn": "web-prod-01.corp.local",
        "os": "Linux",
        "os_version": "Ubuntu 22.04",
        "category": "Web Server",
        "assigned_to": {"display_value": "Bob", "value": "uid-bob"},
        "support_group": {"display_value": "Web Ops", "value": "grp-webops"},
        "sys_created_on": "2023-01-01 00:00:00",
        "sys_updated_on": "2024-05-01 12:00:00",
    },
]

CMDB_RELS_OUTBOUND = [
    {
        "child": {"display_value": "db-prod-01", "value": "ci-db1"},
        "type": {"display_value": "Depends on::Used by", "value": "rel-type-1"},
    },
]

CMDB_RELS_INBOUND = [
    {
        "parent": {"display_value": "load-balancer-01", "value": "ci-lb1"},
        "type": {"display_value": "Depends on::Used by", "value": "rel-type-1"},
    },
]

CHANGES = [
    {
        "sys_id": "chg1",
        "number": "CHG0001234",
        "short_description": "Upgrade web server OS",
        "description": "Patch Ubuntu to 24.04 LTS.",
        "type": {"display_value": "Standard", "value": "standard"},
        "state": {"display_value": "Scheduled", "value": "2"},
        "priority": {"display_value": "3 - Moderate", "value": "3"},
        "risk": {"display_value": "Moderate", "value": "2"},
        "category": "Software",
        "assigned_to": {"display_value": "Charlie", "value": "uid-charlie"},
        "assignment_group": {"display_value": "Change Team", "value": "grp-chg"},
        "cmdb_ci": {"display_value": "web-prod-01", "value": "ci1"},
        "start_date": "2024-07-01 02:00:00",
        "end_date": "2024-07-01 06:00:00",
        "opened_at": "2024-06-15 11:00:00",
        "closed_at": "",
        "sys_created_on": "2024-06-15 11:00:00",
        "sys_updated_on": "2024-06-15 11:00:00",
    },
]

PROBLEMS = [
    {
        "sys_id": "prb1",
        "number": "PRB0000567",
        "short_description": "Recurring email delivery failures",
        "description": "Users report intermittent email bounces.",
        "state": {"display_value": "Known Error", "value": "4"},
        "priority": {"display_value": "2 - High", "value": "2"},
        "category": "network",
        "assigned_to": {"display_value": "Diana", "value": "uid-diana"},
        "assignment_group": {"display_value": "Email Ops", "value": "grp-email"},
        "cmdb_ci": {"display_value": "mail-prod-01", "value": "ci-mail"},
        "cause_notes": "MTA queue overflow under peak load.",
        "known_error": "true",
        "fix_notes": "Increase MTA queue depth to 5000.",
        "opened_at": "2024-04-01 08:00:00",
        "resolved_at": "",
        "closed_at": "",
        "sys_created_on": "2024-04-01 08:00:00",
        "sys_updated_on": "2024-05-20 16:00:00",
    },
]

CATALOG_ITEMS = [
    {
        "sys_id": "cat1",
        "name": "New Laptop Request",
        "short_description": "Request a new corporate laptop",
        "description": "Select model, RAM, and accessories.",
        "category": {"display_value": "Hardware", "value": "hw"},
        "sc_catalogs": {"display_value": "IT Catalog", "value": "sc-it"},
        "price": "1200.00",
        "active": "true",
        "sys_created_on": "2024-01-01 00:00:00",
        "sys_updated_on": "2024-06-01 00:00:00",
    },
    {
        "sys_id": "cat2",
        "name": "Retired VPN Token",
        "short_description": "Legacy VPN token",
        "description": "",
        "category": {"display_value": "Security", "value": "sec"},
        "sc_catalogs": "",
        "price": "",
        "active": "false",
        "sys_created_on": "2020-01-01 00:00:00",
        "sys_updated_on": "2023-01-01 00:00:00",
    },
]

JOURNALS = [
    {
        "value": "Restarted Exchange service, monitoring.",
        "element": "work_notes",
        "sys_created_on": "2024-06-01 09:15:00",
        "sys_created_by": "alice",
    },
    {
        "value": "We are working on the email issue.",
        "element": "comments",
        "sys_created_on": "2024-06-01 09:20:00",
        "sys_created_by": "alice",
    },
]


# ===================================================================
# 1. Pagination — multiple pages of results
# ===================================================================


@responses.activate
def test_pagination_fetches_all_pages() -> None:
    """Records spread across 2 pages must all come through."""
    conn = SnowConnection(instance_url=BASE_URL, username="u", password="p", page_size=1)

    # Page 1: one record
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": [INCIDENTS[0]]})
    # Page 2: one record (signals last page because count < page_size=1 is false, count==1)
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": [INCIDENTS[1]]})
    # Page 3: empty — signals end
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": []})

    loader = IncidentLoader(connection=conn)
    docs = loader.load()

    assert len(docs) == 2
    assert docs[0].metadata["number"] == "INC0010001"
    assert docs[1].metadata["number"] == "INC0010002"

    # Verify pagination offsets were sent correctly
    assert responses.calls[0].request.params["sysparm_offset"] == "0"
    assert responses.calls[1].request.params["sysparm_offset"] == "1"


# ===================================================================
# 2. IncidentLoader — full content + metadata verification
# ===================================================================


@responses.activate
def test_incident_full_document_content() -> None:
    """Incident doc should contain all non-empty fields in structured text."""
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": [INCIDENTS[0]]})

    docs = IncidentLoader(connection=_conn()).load()
    text = docs[0].page_content

    assert "Incident: INC0010001" in text
    assert "Summary: Email server down" in text
    assert "Description: Exchange cluster is unreachable since 09:00." in text
    assert "State: In Progress" in text
    assert "Priority: 1 - Critical" in text
    assert "Category: network / email" in text
    assert "Assigned To: Alice" in text
    assert "Assignment Group: NOC" in text
    assert "Configuration Item: mail-prod-01" in text
    assert "Opened: 2024-06-01 09:00:00" in text


@responses.activate
def test_incident_empty_fields_omitted() -> None:
    """Incident with empty optional fields should skip those lines."""
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": [INCIDENTS[1]]})

    docs = IncidentLoader(connection=_conn()).load()
    text = docs[0].page_content

    # These fields are empty in INCIDENTS[1]
    assert "Description:" not in text
    assert "Assigned To:" not in text
    assert "Assignment Group:" not in text
    assert "Configuration Item:" not in text
    assert "Resolved:" not in text
    assert "Closed:" not in text
    assert "Resolution Notes:" not in text
    # Subcategory empty → just "network" without "/"
    assert "Category: network" in text
    assert "/" not in text.split("Category:")[1].split("\n")[0]


@responses.activate
def test_incident_metadata_includes_raw_values() -> None:
    """Metadata should store raw sys_id values for reference fields."""
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": [INCIDENTS[0]]})

    docs = IncidentLoader(connection=_conn()).load()
    meta = docs[0].metadata

    assert meta["sys_id"] == "inc1"
    assert meta["table"] == "incident"
    assert meta["number"] == "INC0010001"
    assert meta["cmdb_ci"] == "ci-mail"  # raw value, not display
    assert meta["source"].startswith("servicenow://incident/")


@responses.activate
def test_incident_display_value_extraction() -> None:
    """Reference fields (dicts with display_value) must be unpacked for text."""
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": [INCIDENTS[0]]})

    docs = IncidentLoader(connection=_conn()).load()
    text = docs[0].page_content

    # These came from dict fields with display_value
    assert "Alice" in text  # assigned_to.display_value
    assert "NOC" in text  # assignment_group.display_value
    assert "In Progress" in text  # state.display_value


# ===================================================================
# 3. KnowledgeBaseLoader — HTML cleaning
# ===================================================================


@responses.activate
def test_kb_html_cleaning() -> None:
    """KB article HTML should be stripped and entities decoded."""
    responses.add(responses.GET, f"{TABLE_API}/kb_knowledge", json={"result": KB_ARTICLES})

    docs = KnowledgeBaseLoader(connection=_conn()).load()
    text = docs[0].page_content

    # Tags should be gone
    assert "<p>" not in text
    assert "<b>" not in text
    assert "<i>" not in text
    assert "<br" not in text

    # Content preserved, entity decoded
    assert "Settings > VPN" in text  # &gt; decoded
    assert "Click Reset" in text or "Reset" in text

    # Structure
    assert "Article: KB0000101" in text
    assert "Title: How to reset your VPN password" in text


@responses.activate
def test_kb_metadata() -> None:
    """KB metadata should include workflow state and author info."""
    responses.add(responses.GET, f"{TABLE_API}/kb_knowledge", json={"result": KB_ARTICLES})

    docs = KnowledgeBaseLoader(connection=_conn()).load()
    meta = docs[0].metadata

    assert meta["table"] == "kb_knowledge"
    assert meta["number"] == "KB0000101"
    assert meta["workflow_state"] == "published"
    assert meta["source"].startswith("servicenow://kb_knowledge/")


# ===================================================================
# 4. CMDBLoader — relationships, ci_class override
# ===================================================================


@responses.activate
def test_cmdb_with_relationships() -> None:
    """CMDB loader with include_relationships should show dependency graph."""
    # CI records
    responses.add(responses.GET, f"{TABLE_API}/cmdb_ci_server", json={"result": CMDB_CIS})
    # Outbound relationships (parent=ci1)
    responses.add(responses.GET, f"{TABLE_API}/cmdb_rel_ci", json={"result": CMDB_RELS_OUTBOUND})
    # Inbound relationships (child=ci1)
    responses.add(responses.GET, f"{TABLE_API}/cmdb_rel_ci", json={"result": CMDB_RELS_INBOUND})

    loader = CMDBLoader(
        connection=_conn(),
        ci_class="cmdb_ci_server",
        include_relationships=True,
    )
    docs = loader.load()

    text = docs[0].page_content

    assert "Configuration Item: web-prod-01" in text
    assert "Class: cmdb_ci_server" in text
    assert "IP Address: 10.0.1.10" in text
    assert "FQDN: web-prod-01.corp.local" in text
    assert "OS: Linux Ubuntu 22.04" in text

    # Relationships in text
    assert "db-prod-01" in text  # outbound target
    assert "load-balancer-01" in text  # inbound target
    assert "->" in text  # outbound arrow
    assert "<-" in text  # inbound arrow


@responses.activate
def test_cmdb_metadata_has_relationships() -> None:
    """CMDB metadata should include structured relationship lists."""
    responses.add(responses.GET, f"{TABLE_API}/cmdb_ci_server", json={"result": CMDB_CIS})
    responses.add(responses.GET, f"{TABLE_API}/cmdb_rel_ci", json={"result": CMDB_RELS_OUTBOUND})
    responses.add(responses.GET, f"{TABLE_API}/cmdb_rel_ci", json={"result": CMDB_RELS_INBOUND})

    loader = CMDBLoader(connection=_conn(), ci_class="cmdb_ci_server", include_relationships=True)
    docs = loader.load()
    meta = docs[0].metadata

    assert meta["table"] == "cmdb_ci_server"
    assert meta["name"] == "web-prod-01"
    assert meta["ip_address"] == "10.0.1.10"
    assert meta["source"].startswith("servicenow://cmdb_ci_server/")

    # Structured relationships stored as a single combined list
    rels = meta.get("relationships", [])
    assert len(rels) == 2
    outbound = [r for r in rels if r["direction"] == "outbound"]
    inbound = [r for r in rels if r["direction"] == "inbound"]
    assert len(outbound) == 1
    assert len(inbound) == 1
    assert outbound[0]["target"] == "db-prod-01"
    assert outbound[0]["target_sys_id"] == "ci-db1"
    assert inbound[0]["target"] == "load-balancer-01"
    assert inbound[0]["target_sys_id"] == "ci-lb1"


@responses.activate
def test_cmdb_without_relationships() -> None:
    """CMDB with include_relationships=False should not query cmdb_rel_ci."""
    responses.add(responses.GET, f"{TABLE_API}/cmdb_ci", json={"result": CMDB_CIS})

    loader = CMDBLoader(connection=_conn(), include_relationships=False)
    docs = loader.load()

    assert len(docs) == 1
    # Only 1 API call (the CI table), not 3
    assert len(responses.calls) == 1
    # No relationship text
    assert "->" not in docs[0].page_content
    assert "<-" not in docs[0].page_content


@responses.activate
def test_cmdb_ci_class_override() -> None:
    """ci_class parameter should change which table is queried."""
    responses.add(responses.GET, f"{TABLE_API}/cmdb_ci_service", json={"result": []})

    loader = CMDBLoader(connection=_conn(), ci_class="cmdb_ci_service")
    docs = loader.load()

    assert docs == []
    assert "cmdb_ci_service" in responses.calls[0].request.url


# ===================================================================
# 5. ChangeLoader
# ===================================================================


@responses.activate
def test_change_full_document() -> None:
    """Change request doc should include lifecycle and implementation window."""
    responses.add(responses.GET, f"{TABLE_API}/change_request", json={"result": CHANGES})

    docs = ChangeLoader(connection=_conn()).load()
    text = docs[0].page_content

    assert "Change Request: CHG0001234" in text
    assert "Summary: Upgrade web server OS" in text
    assert "Type: Standard" in text
    assert "Risk: Moderate" in text
    assert "Scheduled Start: 2024-07-01 02:00:00" in text
    assert "Scheduled End: 2024-07-01 06:00:00" in text

    meta = docs[0].metadata
    assert meta["table"] == "change_request"
    assert meta["cmdb_ci"] == "ci1"  # raw value
    assert meta["source"].startswith("servicenow://change_request/")


# ===================================================================
# 6. ProblemLoader — known error + boolean + root cause
# ===================================================================


@responses.activate
def test_problem_known_error_fields() -> None:
    """Problem with known_error=true should show root cause and fix."""
    responses.add(responses.GET, f"{TABLE_API}/problem", json={"result": PROBLEMS})

    docs = ProblemLoader(connection=_conn()).load()
    text = docs[0].page_content

    assert "Problem: PRB0000567" in text
    assert "Root Cause: MTA queue overflow under peak load." in text
    assert "Known Error: Yes" in text
    assert "Fix: Increase MTA queue depth to 5000." in text

    meta = docs[0].metadata
    assert meta["table"] == "problem"
    assert meta["known_error"] is True  # boolean, not string
    assert meta["cmdb_ci"] == "ci-mail"


@responses.activate
def test_problem_without_known_error() -> None:
    """Problem with known_error not true should omit known error fields."""
    record = {**PROBLEMS[0], "known_error": "false", "cause_notes": "", "fix_notes": ""}
    responses.add(responses.GET, f"{TABLE_API}/problem", json={"result": [record]})

    docs = ProblemLoader(connection=_conn()).load()
    text = docs[0].page_content

    assert "Known Error:" not in text
    assert "Fix:" not in text
    assert "Root Cause:" not in text
    assert docs[0].metadata["known_error"] is False


# ===================================================================
# 7. CatalogLoader — active boolean
# ===================================================================


@responses.activate
def test_catalog_active_and_inactive() -> None:
    """Catalog should handle active=true/false boolean conversion."""
    responses.add(responses.GET, f"{TABLE_API}/sc_cat_item", json={"result": CATALOG_ITEMS})

    docs = CatalogLoader(connection=_conn()).load()

    # Active item
    assert "Catalog Item: New Laptop Request" in docs[0].page_content
    assert "Price: 1200.00" in docs[0].page_content
    assert docs[0].metadata["active"] is True
    assert docs[0].metadata["table"] == "sc_cat_item"
    assert docs[0].metadata["source"].startswith("servicenow://sc_cat_item/")

    # Inactive item — description is empty so it should be omitted
    assert "Catalog Item: Retired VPN Token" in docs[1].page_content
    assert docs[1].metadata["active"] is False
    # Empty optional fields should be skipped
    assert "Price:" not in docs[1].page_content


# ===================================================================
# 8. Journal entries (work notes + comments)
# ===================================================================


@responses.activate
def test_incident_with_journals() -> None:
    """Journals should be appended to page_content when requested."""
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": [INCIDENTS[0]]})
    responses.add(responses.GET, f"{TABLE_API}/sys_journal_field", json={"result": JOURNALS})

    loader = IncidentLoader(connection=_conn(), include_journals=True)
    docs = loader.load()
    text = docs[0].page_content

    assert "[work_notes]" in text
    assert "Restarted Exchange service, monitoring." in text
    assert "[comments]" in text
    assert "We are working on the email issue." in text
    assert "alice" in text  # author


@responses.activate
def test_incident_without_journals() -> None:
    """Without include_journals, no journal API call should be made."""
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": [INCIDENTS[0]]})

    loader = IncidentLoader(connection=_conn(), include_journals=False)
    docs = loader.load()

    # Only 1 call (incident table), no sys_journal_field call
    assert len(responses.calls) == 1
    assert "[work_notes]" not in docs[0].page_content


# ===================================================================
# 9. Delta sync — load_since
# ===================================================================


@responses.activate
def test_delta_sync_sends_timestamp_filter() -> None:
    """load_since() should add sys_updated_on filter to the query."""
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": [INCIDENTS[0]]})

    since = datetime(2024, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    docs = IncidentLoader(connection=_conn()).load_since(since)

    assert len(docs) == 1
    query = responses.calls[0].request.params["sysparm_query"]
    assert "sys_updated_on>2024-06-01 09:00:00" in query
    # Ordering must still be present
    assert "ORDERBYsys_created_on" in query


@responses.activate
def test_delta_sync_with_existing_query() -> None:
    """Delta sync combined with a user query should produce both filters."""
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": []})

    since = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    loader = IncidentLoader(connection=_conn(), query="active=true^priority=1")
    loader.load_since(since)

    query = responses.calls[0].request.params["sysparm_query"]
    assert "active=true^priority=1" in query
    assert "sys_updated_on>2024-06-01 00:00:00" in query
    assert "ORDERBYsys_created_on" in query


# ===================================================================
# 10. LangChain adapter — end-to-end
# ===================================================================


@responses.activate
def test_langchain_adapter_full_pipeline() -> None:
    """LangChain adapter should produce proper LC Documents end-to-end."""
    __import__("pytest").importorskip("langchain_core")
    from langchain_core.document_loaders import BaseLoader
    from langchain_core.documents import Document

    from snowloader.adapters.langchain import (
        ServiceNowIncidentLoader,
        ServiceNowKBLoader,
    )

    # Incident
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": INCIDENTS})

    loader = ServiceNowIncidentLoader(connection=_conn(), query="active=true")
    assert isinstance(loader, BaseLoader)

    docs = loader.load()
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)
    assert "INC0010001" in docs[0].page_content
    assert docs[0].metadata["table"] == "incident"

    # KB via lazy_load
    responses.add(responses.GET, f"{TABLE_API}/kb_knowledge", json={"result": KB_ARTICLES})

    kb_loader = ServiceNowKBLoader(connection=_conn())
    lc_docs = list(kb_loader.lazy_load())
    assert len(lc_docs) == 1
    assert isinstance(lc_docs[0], Document)
    assert "<p>" not in lc_docs[0].page_content  # HTML cleaned


@responses.activate
def test_langchain_adapter_load_since() -> None:
    """LangChain adapter load_since should pass datetime through."""
    __import__("pytest").importorskip("langchain_core")
    from langchain_core.documents import Document

    from snowloader.adapters.langchain import ServiceNowChangeLoader

    responses.add(responses.GET, f"{TABLE_API}/change_request", json={"result": CHANGES})

    loader = ServiceNowChangeLoader(connection=_conn())
    since = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    docs = loader.load_since(since)

    assert len(docs) == 1
    assert isinstance(docs[0], Document)
    query = responses.calls[0].request.params["sysparm_query"]
    assert "sys_updated_on>2024-06-01 00:00:00" in query


@responses.activate
def test_langchain_adapter_kwargs_passthrough() -> None:
    """Adapter kwargs (ci_class, include_relationships) should reach core loader."""
    __import__("pytest").importorskip("langchain_core")
    from snowloader.adapters.langchain import ServiceNowCMDBLoader

    responses.add(responses.GET, f"{TABLE_API}/cmdb_ci_server", json={"result": CMDB_CIS})
    responses.add(responses.GET, f"{TABLE_API}/cmdb_rel_ci", json={"result": CMDB_RELS_OUTBOUND})
    responses.add(responses.GET, f"{TABLE_API}/cmdb_rel_ci", json={"result": CMDB_RELS_INBOUND})

    loader = ServiceNowCMDBLoader(
        connection=_conn(), ci_class="cmdb_ci_server", include_relationships=True
    )
    docs = loader.load()

    assert len(docs) == 1
    assert "cmdb_ci_server" in responses.calls[0].request.url
    assert "db-prod-01" in docs[0].page_content  # relationship came through


# ===================================================================
# 11. LlamaIndex adapter — end-to-end
# ===================================================================


@responses.activate
def test_llamaindex_adapter_full_pipeline() -> None:
    """LlamaIndex adapter should produce proper LI Documents end-to-end."""
    __import__("pytest").importorskip("llama_index.core")
    from llama_index.core.readers.base import BaseReader
    from llama_index.core.schema import Document

    from snowloader.adapters.llamaindex import (
        ServiceNowIncidentReader,
        ServiceNowProblemReader,
    )

    # Incident
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": INCIDENTS})

    reader = ServiceNowIncidentReader(connection=_conn())
    assert isinstance(reader, BaseReader)

    docs = reader.load_data()
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)
    assert "INC0010001" in docs[0].text
    assert docs[0].metadata["table"] == "incident"
    assert "sys_id" in docs[0].excluded_llm_metadata_keys

    # Problem
    responses.add(responses.GET, f"{TABLE_API}/problem", json={"result": PROBLEMS})

    prb_reader = ServiceNowProblemReader(connection=_conn())
    docs = prb_reader.load_data()
    assert len(docs) == 1
    assert "PRB0000567" in docs[0].text
    assert docs[0].metadata["known_error"] is True


@responses.activate
def test_llamaindex_adapter_load_data_since() -> None:
    """LlamaIndex adapter load_data_since should pass datetime through."""
    __import__("pytest").importorskip("llama_index.core")
    from llama_index.core.schema import Document

    from snowloader.adapters.llamaindex import ServiceNowCatalogReader

    responses.add(responses.GET, f"{TABLE_API}/sc_cat_item", json={"result": CATALOG_ITEMS})

    reader = ServiceNowCatalogReader(connection=_conn())
    since = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    docs = reader.load_data_since(since)

    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)
    query = responses.calls[0].request.params["sysparm_query"]
    assert "sys_updated_on>2024-01-01 00:00:00" in query


@responses.activate
def test_llamaindex_adapter_kwargs_passthrough() -> None:
    """Adapter kwargs should reach the underlying core loader."""
    __import__("pytest").importorskip("llama_index.core")
    from snowloader.adapters.llamaindex import ServiceNowCMDBReader

    responses.add(responses.GET, f"{TABLE_API}/cmdb_ci_server", json={"result": CMDB_CIS})
    responses.add(responses.GET, f"{TABLE_API}/cmdb_rel_ci", json={"result": CMDB_RELS_OUTBOUND})
    responses.add(responses.GET, f"{TABLE_API}/cmdb_rel_ci", json={"result": CMDB_RELS_INBOUND})

    reader = ServiceNowCMDBReader(
        connection=_conn(), ci_class="cmdb_ci_server", include_relationships=True
    )
    docs = reader.load_data()

    assert len(docs) == 1
    assert "load-balancer-01" in docs[0].text


# ===================================================================
# 12. Connection edge cases
# ===================================================================


@responses.activate
def test_connection_trailing_slash_stripped() -> None:
    """Trailing slashes on instance_url must not break API URLs."""
    conn = SnowConnection(instance_url=f"{BASE_URL}///", username="u", password="p")
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": []})

    docs = IncidentLoader(connection=conn).load()
    assert docs == []
    # URL should not have double slashes
    assert "///" not in responses.calls[0].request.url.split("smoke.service-now.com")[1]


@responses.activate
def test_connection_empty_result_set() -> None:
    """Empty API response should yield zero documents, not error."""
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": []})

    docs = IncidentLoader(connection=_conn()).load()
    assert docs == []


@responses.activate
def test_connection_fields_filter() -> None:
    """The fields parameter should send sysparm_fields to the API."""
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": []})

    loader = IncidentLoader(connection=_conn(), fields=["number", "short_description"])
    loader.load()

    assert responses.calls[0].request.params["sysparm_fields"] == "number,short_description"


@responses.activate
def test_connection_query_filter() -> None:
    """The query parameter should appear in sysparm_query."""
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": []})

    loader = IncidentLoader(connection=_conn(), query="active=true^priority=1")
    loader.load()

    query = responses.calls[0].request.params["sysparm_query"]
    assert query.startswith("active=true^priority=1")
    assert "ORDERBYsys_created_on" in query


def test_connection_missing_creds_raises() -> None:
    """SnowConnection without any credentials should raise immediately."""
    import pytest

    from snowloader import SnowConnectionError

    with pytest.raises(SnowConnectionError):
        SnowConnection(instance_url=BASE_URL)


@responses.activate
def test_connection_api_error_raises() -> None:
    """Non-2xx API responses should raise SnowConnectionError."""
    import pytest

    from snowloader import SnowConnectionError

    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"error": {"message": "Access denied"}},
        status=401,
    )

    with pytest.raises(SnowConnectionError, match="401"):
        IncidentLoader(connection=_conn()).load()


# ===================================================================
# 13. HTML cleaner edge cases
# ===================================================================


def test_html_cleaner_empty_string() -> None:
    """Empty input should return empty output."""
    from snowloader.utils.html_cleaner import clean_html

    assert clean_html("") == ""


def test_html_cleaner_plain_text_passthrough() -> None:
    """Plain text without HTML should pass through unchanged."""
    from snowloader.utils.html_cleaner import clean_html

    text = "This is plain text with no HTML."
    assert clean_html(text) == text


def test_html_cleaner_entities_decoded() -> None:
    """HTML entities like &amp; and &lt; should be decoded."""
    from snowloader.utils.html_cleaner import clean_html

    result = clean_html("A &amp; B &lt; C &gt; D")
    assert result == "A & B < C > D"


def test_html_cleaner_consecutive_blank_lines_collapsed() -> None:
    """Multiple blank lines should be collapsed to one."""
    from snowloader.utils.html_cleaner import clean_html

    html = "<p>Paragraph 1</p><p></p><p></p><p>Paragraph 2</p>"
    result = clean_html(html)
    lines = result.split("\n")

    # Should not have more than one consecutive blank line
    consecutive_blanks = 0
    for line in lines:
        if line.strip() == "":
            consecutive_blanks += 1
            assert consecutive_blanks <= 1
        else:
            consecutive_blanks = 0


def test_html_cleaner_br_tags_become_newlines() -> None:
    """BR tags in various forms should become newlines."""
    from snowloader.utils.html_cleaner import clean_html

    result = clean_html("Line1<br>Line2<br/>Line3<BR />Line4")
    assert "Line1" in result
    assert "Line2" in result
    assert "Line3" in result
    assert "Line4" in result
    assert "<br" not in result.lower()


# ===================================================================
# 14. Full pipeline: connection → loader → adapter → verify
# ===================================================================


@responses.activate
def test_full_pipeline_incident_through_both_adapters() -> None:
    """Same data through both adapters should produce equivalent content."""
    __import__("pytest").importorskip("langchain_core")
    __import__("pytest").importorskip("llama_index.core")

    from langchain_core.documents import Document as LCDoc
    from llama_index.core.schema import Document as LIDoc

    from snowloader.adapters.langchain import ServiceNowIncidentLoader
    from snowloader.adapters.llamaindex import ServiceNowIncidentReader

    conn = _conn()

    # LangChain path
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": [INCIDENTS[0]]})
    lc_docs = ServiceNowIncidentLoader(connection=conn).load()

    # LlamaIndex path
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": [INCIDENTS[0]]})
    li_docs = ServiceNowIncidentReader(connection=conn).load_data()

    # Both should have the same content
    assert isinstance(lc_docs[0], LCDoc)
    assert isinstance(li_docs[0], LIDoc)
    assert lc_docs[0].page_content == li_docs[0].text
    assert lc_docs[0].metadata["sys_id"] == li_docs[0].metadata["sys_id"]
    assert lc_docs[0].metadata["table"] == li_docs[0].metadata["table"]

    # LlamaIndex-specific: sys_id excluded from LLM
    assert "sys_id" in li_docs[0].excluded_llm_metadata_keys


# ===================================================================
# 15. lazy_load is a generator (streaming, not list)
# ===================================================================


@responses.activate
def test_lazy_load_is_generator() -> None:
    """lazy_load() should yield documents one at a time, not load all."""
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": INCIDENTS})

    loader = IncidentLoader(connection=_conn())
    gen = loader.lazy_load()

    # Should be a generator, not a list
    import types

    assert isinstance(gen, types.GeneratorType)

    # Pull one at a time
    first = next(gen)
    assert first.metadata["number"] == "INC0010001"

    second = next(gen)
    assert second.metadata["number"] == "INC0010002"
