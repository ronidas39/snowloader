Loaders
=======

snowloader provides a loader for each of the core ServiceNow tables, plus a
generic one for everything else. All of them share the same interface
inherited from :class:`~snowloader.models.BaseSnowLoader`:

- ``load()`` - returns a list of all matching documents
- ``lazy_load()`` - yields documents one at a time (memory efficient)
- ``load_since(datetime)`` - delta sync, fetches only records that changed
- ``concurrent_load(max_workers)`` - the threaded paginator
- ``concurrent_lazy_load(...)`` - the threaded paginator, streaming

Every one of those takes ``verify=True`` to raise rather than return an
incomplete extract, and ``on_error="skip"`` to finish past a page that could
not be fetched. See :doc:`verification`.

Every one of them also takes ``expand_references`` and ``include_raw``, which
control how much of the record reaches document metadata. See
:doc:`references`.

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

Loads Configuration Items from any CMDB class table. It can optionally
traverse the relationship graph to show how CIs depend on each other, though
for more than a handful of CIs :class:`~snowloader.RelationshipLoader` is the
better tool. See below.

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

- ``ci_class`` - CMDB class table (default: ``"cmdb_ci"``). Use
  ``"cmdb_ci_server"``, ``"cmdb_ci_service"``, etc. for specific classes.
- ``include_relationships`` - when ``True``, fetches outbound and inbound
  relationships from ``cmdb_rel_ci``. Adds 2 API calls per CI.
- ``max_relationship_workers`` - number of concurrent threads for
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
cause, known error status, and fix notes - the fields most valuable for
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

RelationshipLoader
------------------

Sweeps ``cmdb_rel_ci`` and returns one document per edge. Both endpoints and
the relationship type arrive as sys_ids alongside their labels, so the result
loads into a graph with no resolution step.

.. code-block:: python

   from snowloader import RelationshipLoader

   for doc in RelationshipLoader(connection=conn).lazy_load(verify=True):
       graph.add_edge(
           doc.metadata["parent_sys_id"],
           doc.metadata["child_sys_id"],
           type=doc.metadata["type"],
       )

Prefer this over :class:`~snowloader.CMDBLoader` with
``include_relationships=True`` for anything more than a handful of CIs. That
option issues two extra requests per configuration item. Measured on a
developer instance, that came to 2.4 seconds per CI, which projects to about
34 hours for a 50,000 CI estate. Sweeping the whole ``cmdb_rel_ci`` table on
the same instance took 7 seconds and returned every edge.

Pass ``query`` to narrow it, for instance ``f"parent={sys_id}"`` for one CI's
outbound edges, or a type filter for one kind of relationship.

TableLoader
-----------

A loader for any table that does not have a dedicated one. Same document
shape, same metadata treatment, no subclassing.

.. code-block:: python

   from snowloader import TableLoader

   loader = TableLoader(
       connection=conn,
       table="sc_task",
       query="active=true",
   )
   for doc in loader.lazy_load():
       print(doc.metadata["assignment_group_sys_id"])

Page content comes from ``content_fields`` when you give them:

.. code-block:: python

   TableLoader(
       conn,
       table="sys_user",
       content_fields=["name", "title", "department"],
   )

When you do not, the loader uses whichever of the usual text columns the
record actually has (``short_description``, ``description``, ``name``,
``title``, ``text``, ``comments``, ``close_notes``, ``work_notes``), so an
unfamiliar table still produces something readable. A link table with no text
at all produces documents with empty content and full metadata, which is the
right answer for that shape rather than an error.
