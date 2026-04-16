Advanced Usage
==============

Delta Sync
----------

Only fetch records that changed since your last sync. This is essential
for keeping a vector store up to date without re-processing the entire
table on every run.

.. code-block:: python

   from datetime import datetime, timezone
   from snowloader import SnowConnection, IncidentLoader

   conn = SnowConnection(instance_url="...", username="...", password="...")
   loader = IncidentLoader(connection=conn)

   # First run: load everything
   docs = loader.load()
   last_sync = datetime.now(timezone.utc)

   # Subsequent runs: only get updates
   updated_docs = loader.load_since(last_sync)
   last_sync = datetime.now(timezone.utc)

Under the hood, ``load_since()`` appends a
``sys_updated_on>{timestamp}`` filter to the query. It works with all
six loaders and both framework adapters.

CMDB Relationship Traversal
----------------------------

The CMDB loader can map out how Configuration Items relate to each
other - dependencies, containment, hosting, and more.

.. code-block:: python

   from snowloader import CMDBLoader

   loader = CMDBLoader(
       connection=conn,
       ci_class="cmdb_ci_service",
       include_relationships=True,
       query="operational_status=1",
   )

   for doc in loader.lazy_load():
       # Document text includes relationship arrows:
       #   -> Database Server (Depends on::Used by)
       #   <- Email Service (Depends on::Used by)
       print(doc.page_content)

       # Structured relationship data in metadata
       for rel in doc.metadata.get("relationships", []):
           print(
               f"  {rel['direction']}: {rel['target']} "
               f"(sys_id: {rel['target_sys_id']}, type: {rel['type']})"
           )

Relationship fetching uses concurrent threads (configurable via
``max_relationship_workers``). If one direction fails (e.g., outbound
times out), the other direction's data is still preserved.

Journal Entries (Work Notes & Comments)
---------------------------------------

Incidents, changes, and problems can include journal entries - the
timestamped notes that agents add during investigation. These are stored
in a separate table (``sys_journal_field``) and fetched per record when
``include_journals=True``.

.. code-block:: python

   from snowloader import IncidentLoader

   loader = IncidentLoader(
       connection=conn,
       query="active=true",
       include_journals=True,
   )

   for doc in loader.lazy_load():
       if "[work_notes]" in doc.page_content:
           print(f"{doc.metadata['number']} has work notes")

Journal fetching is resilient - if the journal table is inaccessible
(permissions, network error), a warning is logged and the document is
returned without journal data rather than failing the entire load.

Context Manager
---------------

Use ``SnowConnection`` as a context manager to ensure the HTTP session
is properly closed when you are done:

.. code-block:: python

   with SnowConnection(instance_url="...", username="...", password="...") as conn:
       docs = IncidentLoader(connection=conn).load()
       # Session is closed automatically at the end of the block

Rate Limiting
-------------

ServiceNow instances enforce rate limits (typically ~600 requests per
minute for cloud instances). Use the ``request_delay`` parameter to
pace your requests:

.. code-block:: python

   conn = SnowConnection(
       instance_url="...",
       username="...",
       password="...",
       request_delay=0.1,  # 100ms between requests (~600 req/min)
   )

The connection also handles HTTP 429 responses automatically - it reads
the ``Retry-After`` header and waits before retrying.

Filtering with Encoded Queries
------------------------------

The ``query`` parameter accepts ServiceNow encoded query syntax. Some
common patterns:

.. code-block:: python

   # Active, high-priority incidents
   query = "active=true^priority<=2"

   # Incidents assigned to a specific group
   query = "assignment_group.name=Network Operations"

   # Changes scheduled in the next 7 days
   query = "start_date>javascript:gs.beginningOfToday()^start_date<javascript:gs.daysAgoEnd(-7)"

   # KB articles in a specific knowledge base
   query = "kb_knowledge_base.title=IT Knowledge Base^workflow_state=published"

   # CMDB servers in production
   query = "operational_status=1^environment=production"

Refer to the `ServiceNow encoded query documentation
<https://docs.servicenow.com/bundle/latest/page/use/common-ui-elements/reference/r_OpAvailableFiltersQueries.html>`_
for the full syntax reference.

Custom Field Selection
----------------------

By default, loaders request all fields from the API. Use the ``fields``
parameter to limit which fields are returned, reducing payload size and
API response time:

.. code-block:: python

   loader = IncidentLoader(
       connection=conn,
       fields=["number", "short_description", "state", "priority", "sys_id"],
   )
