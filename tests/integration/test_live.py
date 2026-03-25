"""Live integration tests against a real ServiceNow developer instance.

These tests hit the actual ServiceNow Table API — no mocking. They verify
that the full pipeline (connection → loader → adapter) works end-to-end
with real data, real pagination, real reference fields, and real display
values.

Requires environment variables:
    SNOW_INSTANCE  — e.g. https://dev270102.service-now.com
    SNOW_USER      — e.g. admin
    SNOW_PASS      — e.g. password

Run with:
    pytest tests/integration/test_live.py -x --tb=short -v

Author: Roni Das
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from snowloader import (
    CatalogLoader,
    ChangeLoader,
    CMDBLoader,
    IncidentLoader,
    KnowledgeBaseLoader,
    ProblemLoader,
    SnowConnection,
)

# Skip entire module if credentials are not set
INSTANCE = os.environ.get("SNOW_INSTANCE", "")
USER = os.environ.get("SNOW_USER", "")
PASS = os.environ.get("SNOW_PASS", "")

pytestmark = pytest.mark.skipif(
    not all([INSTANCE, USER, PASS]),
    reason="SNOW_INSTANCE, SNOW_USER, SNOW_PASS env vars required",
)


@pytest.fixture(scope="module")
def conn() -> SnowConnection:
    """Shared connection for all tests in this module."""
    return SnowConnection(instance_url=INSTANCE, username=USER, password=PASS)


# ===================================================================
# 1. Connection basics
# ===================================================================


def test_connection_can_reach_instance(conn: SnowConnection) -> None:
    """Verify we can talk to the ServiceNow API at all."""
    records = list(conn.get_records("incident", fields=["number"], since=None))
    assert len(records) > 0


def test_connection_pagination(conn: SnowConnection) -> None:
    """Pagination with small page_size should still return all records."""
    small_conn = SnowConnection(instance_url=INSTANCE, username=USER, password=PASS, page_size=5)
    # Fetch up to 15 to verify pagination happens
    count = 0
    for _ in small_conn.get_records("incident", fields=["number"]):
        count += 1
        if count >= 15:
            break
    assert count >= 15, "Expected at least 15 incidents for pagination test"


def test_connection_fields_filter(conn: SnowConnection) -> None:
    """Requesting specific fields should return only those fields."""
    records = list(conn.get_records("incident", fields=["number", "state"]))
    assert len(records) > 0
    first = records[0]
    # Should have the fields we asked for
    assert "number" in first
    assert "state" in first


def test_connection_query_filter(conn: SnowConnection) -> None:
    """Query filter should limit results."""
    all_records = list(conn.get_records("incident", fields=["number"]))
    filtered = list(conn.get_records("incident", query="active=true", fields=["number"]))
    # Filtered should be <= total (could be equal if all active)
    assert len(filtered) <= len(all_records)


def test_connection_empty_result(conn: SnowConnection) -> None:
    """A query that matches nothing should return empty, not error."""
    records = list(
        conn.get_records(
            "incident",
            query="number=INC9999999999",
            fields=["number"],
        )
    )
    assert records == []


# ===================================================================
# 2. IncidentLoader — real data
# ===================================================================


def test_incident_loader_returns_documents(conn: SnowConnection) -> None:
    """IncidentLoader should return SnowDocuments from real incidents."""
    loader = IncidentLoader(connection=conn)
    docs = loader.load()
    assert len(docs) > 0

    doc = docs[0]
    assert doc.page_content
    assert "Incident:" in doc.page_content
    assert doc.metadata["table"] == "incident"
    assert doc.metadata["sys_id"]
    assert doc.metadata["number"].startswith("INC")


def test_incident_display_values_resolved(conn: SnowConnection) -> None:
    """Reference fields should show human names, not sys_ids."""
    loader = IncidentLoader(connection=conn, query="assigned_toISNOTEMPTY")
    docs = loader.load()
    assert len(docs) > 0

    doc = docs[0]
    text = doc.page_content

    # State should be a word like "New", "In Progress", "Closed" — not "1", "2", "7"
    state = doc.metadata.get("state", "")
    assert state, "State should not be empty"
    assert not state.isdigit(), f"State '{state}' looks like a raw value, not a display value"

    # Assigned To should be a name, not a 32-char sys_id
    assert "Assigned To:" in text
    assigned_line = [line for line in text.split("\n") if "Assigned To:" in line]
    if assigned_line:
        name_part = assigned_line[0].split("Assigned To:")[1].strip()
        assert len(name_part) < 32, f"Assigned To '{name_part}' looks like a sys_id, not a name"


def test_incident_lazy_load_is_generator(conn: SnowConnection) -> None:
    """lazy_load() should yield documents one at a time."""
    import types

    loader = IncidentLoader(connection=conn)
    gen = loader.lazy_load()
    assert isinstance(gen, types.GeneratorType)

    first = next(gen)
    assert first.page_content
    assert first.metadata["number"].startswith("INC")


def test_incident_with_journals(conn: SnowConnection) -> None:
    """include_journals=True should append work notes to the document."""
    loader = IncidentLoader(connection=conn, include_journals=True)
    docs = loader.load()

    # At least some incidents should have journals
    docs_with_journals = [
        d for d in docs if "[work_notes]" in d.page_content or "[comments]" in d.page_content
    ]
    assert len(docs_with_journals) > 0, "Expected at least one incident with journal entries"

    doc = docs_with_journals[0]
    assert "by " in doc.page_content  # journal header includes "by author"


def test_incident_without_journals(conn: SnowConnection) -> None:
    """include_journals=False should not include work notes."""
    loader = IncidentLoader(connection=conn, include_journals=False)
    docs = loader.load()
    assert len(docs) > 0

    # No doc should have journal markers
    for doc in docs[:10]:
        assert "[work_notes]" not in doc.page_content
        assert "[comments]" not in doc.page_content


def test_incident_metadata_has_raw_cmdb_ci(conn: SnowConnection) -> None:
    """cmdb_ci in metadata should be a raw sys_id, not a display name."""
    loader = IncidentLoader(connection=conn, query="cmdb_ciISNOTEMPTY")
    docs = loader.load()
    if not docs:
        pytest.skip("No incidents with cmdb_ci set")

    ci = docs[0].metadata.get("cmdb_ci", "")
    assert ci, "cmdb_ci should not be empty"
    # Raw sys_id is 32 hex chars
    assert len(ci) == 32, f"cmdb_ci '{ci}' doesn't look like a sys_id"


# ===================================================================
# 3. KnowledgeBaseLoader — HTML cleaning
# ===================================================================


def test_kb_loader_returns_documents(conn: SnowConnection) -> None:
    """KnowledgeBaseLoader should return documents from real KB articles."""
    loader = KnowledgeBaseLoader(connection=conn)
    docs = loader.load()
    assert len(docs) > 0

    doc = docs[0]
    assert "Article:" in doc.page_content
    assert doc.metadata["table"] == "kb_knowledge"
    assert doc.metadata["number"].startswith("KB")


def test_kb_html_is_cleaned(conn: SnowConnection) -> None:
    """KB article text should have HTML tags stripped."""
    loader = KnowledgeBaseLoader(connection=conn)
    docs = loader.load()
    assert len(docs) > 0

    # Check that no docs contain raw HTML tags
    for doc in docs[:10]:
        assert "<p>" not in doc.page_content, (
            f"Found raw <p> tag in KB doc {doc.metadata.get('number')}"
        )
        assert "<div>" not in doc.page_content, (
            f"Found raw <div> tag in KB doc {doc.metadata.get('number')}"
        )


# ===================================================================
# 4. CMDBLoader — relationships
# ===================================================================


def test_cmdb_loader_returns_documents(conn: SnowConnection) -> None:
    """CMDBLoader should return CI documents."""
    loader = CMDBLoader(connection=conn, ci_class="cmdb_ci_server")
    docs = loader.load()
    assert len(docs) > 0

    doc = docs[0]
    assert "Configuration Item:" in doc.page_content
    assert doc.metadata["table"] == "cmdb_ci_server"
    assert doc.metadata["sys_id"]
    assert doc.metadata["name"]


def test_cmdb_ci_class_override(conn: SnowConnection) -> None:
    """ci_class parameter should query the right table."""
    loader_server = CMDBLoader(connection=conn, ci_class="cmdb_ci_server")
    loader_base = CMDBLoader(connection=conn)

    server_docs = loader_server.load()
    base_docs = loader_base.load()

    assert len(server_docs) > 0
    assert len(base_docs) > 0
    # Server table is a subset of base cmdb_ci
    assert len(server_docs) <= len(base_docs)
    assert server_docs[0].metadata["table"] == "cmdb_ci_server"
    assert base_docs[0].metadata["table"] == "cmdb_ci"


def test_cmdb_with_relationships(conn: SnowConnection) -> None:
    """CMDB with include_relationships should include relationship data."""
    loader = CMDBLoader(
        connection=conn,
        ci_class="cmdb_ci_server",
        include_relationships=True,
    )
    docs = loader.load()
    assert len(docs) > 0

    # At least some CIs should have relationships
    docs_with_rels = [
        d for d in docs if d.metadata.get("relationships") and len(d.metadata["relationships"]) > 0
    ]
    assert len(docs_with_rels) > 0, "Expected at least one server CI with relationships"

    rel_doc = docs_with_rels[0]
    rels = rel_doc.metadata["relationships"]
    # Each relationship should have the expected structure
    for rel in rels:
        assert "target" in rel
        assert "direction" in rel
        assert rel["direction"] in ("outbound", "inbound")
        assert "type" in rel

    # Relationship should also appear in the text
    text = rel_doc.page_content
    assert "Relationships:" in text
    assert ("->" in text) or ("<-" in text)


def test_cmdb_without_relationships(conn: SnowConnection) -> None:
    """CMDB without relationships should not have relationship metadata."""
    loader = CMDBLoader(connection=conn, ci_class="cmdb_ci_server", include_relationships=False)
    docs = loader.load()
    assert len(docs) > 0
    # No relationships key in metadata
    assert "relationships" not in docs[0].metadata


# ===================================================================
# 5. ChangeLoader
# ===================================================================


def test_change_loader_returns_documents(conn: SnowConnection) -> None:
    """ChangeLoader should return change request documents."""
    loader = ChangeLoader(connection=conn)
    docs = loader.load()
    assert len(docs) > 0

    doc = docs[0]
    assert "Change Request:" in doc.page_content
    assert doc.metadata["table"] == "change_request"
    assert doc.metadata["number"].startswith("CHG")


def test_change_display_values(conn: SnowConnection) -> None:
    """Change fields like state and risk should show display values."""
    loader = ChangeLoader(connection=conn)
    docs = loader.load()
    assert len(docs) > 0

    state = docs[0].metadata.get("state", "")
    assert state, "State should not be empty"
    assert not state.isdigit(), f"Change state '{state}' looks like a raw value"


# ===================================================================
# 6. ProblemLoader
# ===================================================================


def test_problem_loader_returns_documents(conn: SnowConnection) -> None:
    """ProblemLoader should return problem documents."""
    loader = ProblemLoader(connection=conn)
    docs = loader.load()
    assert len(docs) > 0

    doc = docs[0]
    assert "Problem:" in doc.page_content
    assert doc.metadata["table"] == "problem"
    assert doc.metadata["number"].startswith("PRB")


def test_problem_known_error_is_boolean(conn: SnowConnection) -> None:
    """known_error metadata should be a Python boolean."""
    loader = ProblemLoader(connection=conn)
    docs = loader.load()
    assert len(docs) > 0

    for doc in docs:
        ke = doc.metadata.get("known_error")
        assert isinstance(ke, bool), f"known_error should be bool, got {type(ke)}: {ke}"


# ===================================================================
# 7. CatalogLoader
# ===================================================================


def test_catalog_loader_returns_documents(conn: SnowConnection) -> None:
    """CatalogLoader should return service catalog documents."""
    loader = CatalogLoader(connection=conn)
    docs = loader.load()
    assert len(docs) > 0

    doc = docs[0]
    assert "Catalog Item:" in doc.page_content
    assert doc.metadata["table"] == "sc_cat_item"
    assert doc.metadata["name"]


def test_catalog_active_is_boolean(conn: SnowConnection) -> None:
    """active metadata should be a Python boolean."""
    loader = CatalogLoader(connection=conn)
    docs = loader.load()
    assert len(docs) > 0

    for doc in docs[:10]:
        active = doc.metadata.get("active")
        assert isinstance(active, bool), f"active should be bool, got {type(active)}: {active}"


# ===================================================================
# 8. Delta sync
# ===================================================================


def test_delta_sync_returns_subset(conn: SnowConnection) -> None:
    """load_since with a recent date should return fewer records."""
    loader = IncidentLoader(connection=conn)
    all_docs = loader.load()

    since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    delta_docs = loader.load_since(since)

    assert len(delta_docs) <= len(all_docs)
    assert len(delta_docs) > 0, "Expected at least some incidents updated since 2020"


def test_delta_sync_far_future_returns_empty(conn: SnowConnection) -> None:
    """load_since with a future date should return zero results."""
    loader = IncidentLoader(connection=conn)
    since = datetime(2099, 1, 1, tzinfo=timezone.utc)
    docs = loader.load_since(since)
    assert docs == []


# ===================================================================
# 9. LangChain adapter — real data
# ===================================================================


def test_langchain_adapter_load(conn: SnowConnection) -> None:
    """LangChain adapter should produce real LC Documents."""
    pytest.importorskip("langchain_core")
    from langchain_core.document_loaders import BaseLoader
    from langchain_core.documents import Document

    from snowloader.adapters.langchain import ServiceNowIncidentLoader

    loader = ServiceNowIncidentLoader(connection=conn, query="active=true")
    assert isinstance(loader, BaseLoader)

    docs = loader.load()
    assert len(docs) > 0
    assert isinstance(docs[0], Document)
    assert "Incident:" in docs[0].page_content
    assert docs[0].metadata["table"] == "incident"


def test_langchain_adapter_lazy_load(conn: SnowConnection) -> None:
    """LangChain lazy_load should yield Documents one at a time."""
    pytest.importorskip("langchain_core")
    from langchain_core.documents import Document

    from snowloader.adapters.langchain import ServiceNowKBLoader

    loader = ServiceNowKBLoader(connection=conn)
    docs = list(loader.lazy_load())
    assert len(docs) > 0
    assert isinstance(docs[0], Document)
    assert "<p>" not in docs[0].page_content  # HTML cleaned


def test_langchain_adapter_load_since(conn: SnowConnection) -> None:
    """LangChain load_since should work with real delta sync."""
    pytest.importorskip("langchain_core")
    from langchain_core.documents import Document

    from snowloader.adapters.langchain import ServiceNowChangeLoader

    loader = ServiceNowChangeLoader(connection=conn)
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    docs = loader.load_since(since)
    assert len(docs) > 0
    assert isinstance(docs[0], Document)


def test_langchain_adapter_all_loaders(conn: SnowConnection) -> None:
    """All 6 LangChain adapter classes should work against real data."""
    pytest.importorskip("langchain_core")

    from snowloader.adapters.langchain import (
        ServiceNowCatalogLoader,
        ServiceNowChangeLoader,
        ServiceNowCMDBLoader,
        ServiceNowIncidentLoader,
        ServiceNowKBLoader,
        ServiceNowProblemLoader,
    )

    adapters = [
        ("Incident", ServiceNowIncidentLoader(connection=conn)),
        ("KB", ServiceNowKBLoader(connection=conn)),
        ("CMDB", ServiceNowCMDBLoader(connection=conn)),
        ("Change", ServiceNowChangeLoader(connection=conn)),
        ("Problem", ServiceNowProblemLoader(connection=conn)),
        ("Catalog", ServiceNowCatalogLoader(connection=conn)),
    ]

    for name, loader in adapters:
        docs = loader.load()
        assert len(docs) > 0, f"{name} adapter returned no documents"


# ===================================================================
# 10. LlamaIndex adapter — real data
# ===================================================================


def test_llamaindex_adapter_load_data(conn: SnowConnection) -> None:
    """LlamaIndex adapter should produce real LI Documents."""
    pytest.importorskip("llama_index.core")
    from llama_index.core.readers.base import BaseReader
    from llama_index.core.schema import Document

    from snowloader.adapters.llamaindex import ServiceNowIncidentReader

    reader = ServiceNowIncidentReader(connection=conn, query="active=true")
    assert isinstance(reader, BaseReader)

    docs = reader.load_data()
    assert len(docs) > 0
    assert isinstance(docs[0], Document)
    assert "Incident:" in docs[0].text
    assert "sys_id" in docs[0].excluded_llm_metadata_keys


def test_llamaindex_adapter_load_data_since(conn: SnowConnection) -> None:
    """LlamaIndex load_data_since should work with real delta sync."""
    pytest.importorskip("llama_index.core")
    from llama_index.core.schema import Document

    from snowloader.adapters.llamaindex import ServiceNowProblemReader

    reader = ServiceNowProblemReader(connection=conn)
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    docs = reader.load_data_since(since)
    assert len(docs) > 0
    assert isinstance(docs[0], Document)


def test_llamaindex_adapter_all_readers(conn: SnowConnection) -> None:
    """All 6 LlamaIndex reader classes should work against real data."""
    pytest.importorskip("llama_index.core")

    from snowloader.adapters.llamaindex import (
        ServiceNowCatalogReader,
        ServiceNowChangeReader,
        ServiceNowCMDBReader,
        ServiceNowIncidentReader,
        ServiceNowKBReader,
        ServiceNowProblemReader,
    )

    readers = [
        ("Incident", ServiceNowIncidentReader(connection=conn)),
        ("KB", ServiceNowKBReader(connection=conn)),
        ("CMDB", ServiceNowCMDBReader(connection=conn)),
        ("Change", ServiceNowChangeReader(connection=conn)),
        ("Problem", ServiceNowProblemReader(connection=conn)),
        ("Catalog", ServiceNowCatalogReader(connection=conn)),
    ]

    for name, reader in readers:
        docs = reader.load_data()
        assert len(docs) > 0, f"{name} reader returned no documents"


# ===================================================================
# 11. Cross-adapter parity
# ===================================================================


def test_both_adapters_produce_same_content(conn: SnowConnection) -> None:
    """LangChain and LlamaIndex should produce identical content."""
    pytest.importorskip("langchain_core")
    pytest.importorskip("llama_index.core")

    from snowloader.adapters.langchain import ServiceNowIncidentLoader
    from snowloader.adapters.llamaindex import ServiceNowIncidentReader

    lc_docs = ServiceNowIncidentLoader(connection=conn, query="active=true").load()
    li_docs = ServiceNowIncidentReader(connection=conn, query="active=true").load_data()

    assert len(lc_docs) == len(li_docs)
    assert len(lc_docs) > 0

    # First doc should have identical content
    assert lc_docs[0].page_content == li_docs[0].text
    assert lc_docs[0].metadata["sys_id"] == li_docs[0].metadata["sys_id"]
