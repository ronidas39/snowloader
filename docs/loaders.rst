Loaders
=======

snowloader provides six loaders, each targeting a specific ServiceNow table.
All loaders share the same interface inherited from
:class:`~snowloader.models.BaseSnowLoader`:

- ``load()`` — returns a list of all matching documents
- ``lazy_load()`` — yields documents one at a time (memory efficient)
- ``load_since(datetime)`` — delta sync, fetches only updated records

IncidentLoader
--------------

Loads IT incidents from the ``incident`` table. Documents include the
incident number, summary, description, state, priority, category,
assignment details, and relevant timestamps.

.. code-block:: python

   from snowloader import SnowConnection, IncidentLoader

   conn = SnowConnection(instance_url="...", username="...", password="...")

   loader = IncidentLoader(
       connection=conn,
       query="active=true^priority<=2",
       include_journals=True,  # Append work notes and comments
   )

   for doc in loader.lazy_load():
       print(doc.metadata["number"], doc.metadata["state"])

**With journal entries:**

When ``include_journals=True``, work notes and comments from
``sys_journal_field`` are appended to the document text. This is useful
for capturing the full investigation history.

KnowledgeBaseLoader
-------------------

Loads articles from the ``kb_knowledge`` table. HTML content is
automatically stripped using the built-in cleaner (no BeautifulSoup
dependency). Falls back to the ``wiki`` field when ``text`` is empty.

.. code-block:: python

   from snowloader import KnowledgeBaseLoader

   loader = KnowledgeBaseLoader(
       connection=conn,
       query="workflow_state=published",
   )

   for doc in loader.lazy_load():
       # Clean plain text, no HTML tags
       print(doc.page_content[:300])

CMDBLoader
----------

Loads Configuration Items from any CMDB class table. The most powerful
loader — it can optionally traverse the relationship graph to show how
CIs depend on each other.

.. code-block:: python

   from snowloader import CMDBLoader

   # Load servers with their dependency graph
   loader = CMDBLoader(
       connection=conn,
       ci_class="cmdb_ci_server",
       include_relationships=True,
       max_relationship_workers=2,  # Concurrent threads for relationship queries
   )

   for doc in loader.lazy_load():
       print(doc.page_content)
       # Document text includes:
       #   -> db-prod-01 (Depends on::Used by)
       #   <- load-balancer-01 (Depends on::Used by)

       # Structured data also in metadata
       for rel in doc.metadata.get("relationships", []):
           print(f"  {rel['direction']}: {rel['target']} ({rel['type']})")

**Parameters:**

- ``ci_class`` — CMDB class table (default: ``"cmdb_ci"``). Use
  ``"cmdb_ci_server"``, ``"cmdb_ci_service"``, etc. for specific classes.
- ``include_relationships`` — when ``True``, fetches outbound and inbound
  relationships from ``cmdb_rel_ci``. Adds 2 API calls per CI.
- ``max_relationship_workers`` — number of concurrent threads for
  relationship queries (default: ``2``).

ChangeLoader
------------

Loads change requests from the ``change_request`` table. Documents emphasize
the change type, risk level, implementation window, and assignment.

.. code-block:: python

   from snowloader import ChangeLoader

   loader = ChangeLoader(connection=conn, query="state=2")  # Scheduled
   docs = loader.load()

ProblemLoader
-------------

Loads problem records from the ``problem`` table. Documents highlight root
cause, known error status, and fix notes — the fields most valuable for
LLM-powered incident correlation.

.. code-block:: python

   from snowloader import ProblemLoader

   loader = ProblemLoader(connection=conn, query="known_error=true")
   for doc in loader.lazy_load():
       if doc.metadata["known_error"]:  # Python bool, not string
           print(f"{doc.metadata['number']}: {doc.page_content[:200]}")

CatalogLoader
-------------

Loads service catalog items from the ``sc_cat_item`` table. Useful for
building LLM-powered service desk chatbots that help users find and
request services.

.. code-block:: python

   from snowloader import CatalogLoader

   loader = CatalogLoader(connection=conn, query="active=true")
   docs = loader.load()
