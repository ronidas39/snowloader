Reference Fields
================

A graph is built out of identifiers. ServiceNow returns most fields as two
values at once: a label meant for a person and a value meant for a join.
Reading the wrong half is easy and fails quietly. This page covers how
snowloader surfaces both.

.. contents::
   :local:
   :depth: 1


The three shapes a field arrives in
-----------------------------------

Which shape you get depends on ``display_value`` on the connection:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Setting
     - Shape
   * - ``"true"`` (default)
     - ``{"display_value": "David Loo", "link": "https://.../sys_user/<sys_id>"}``
   * - ``"all"``
     - ``{"display_value": "David Loo", "value": "<sys_id>"}``
   * - ``"false"``
     - ``"<sys_id>"``

Both halves are present in the first two. The difference is only where the
identifier lives: in a ``value`` key, or in the last path segment of a
``link``.


What loaders put in metadata
----------------------------

Since 0.3.0 every field on a record reaches document metadata, and any field
whose two halves differ gains a companion key beside it.

.. raw:: html

   <div class="snow-figure">
     <img alt="Incident metadata before and after 0.3.0" src="_static/references.png">
     <p class="snow-caption">The same incident, read the same way. Before, the primary key was the string
     form of a dict, cmdb_ci held an identifier where its siblings held labels, and the caller was missing entirely.</p>
   </div>

In code:

.. code-block:: python

   from snowloader import SnowConnection, IncidentLoader

   conn = SnowConnection(..., display_value="all")
   doc = IncidentLoader(conn).load()[0]

   doc.metadata["assignment_group"]         # 'Service Desk'
   doc.metadata["assignment_group_sys_id"]  # 'd625dcce...'

   doc.metadata["caller_id"]                # 'survey user'
   doc.metadata["caller_id_sys_id"]         # '005d500b...'

   doc.metadata["priority"]                 # '5 - Planning'
   doc.metadata["priority_value"]           # '5'

The suffix names what the companion holds. ``_sys_id`` when the value
identifies another record, so anything under a ``_sys_id`` key can be joined
on. ``_value`` when it does not, which is how a choice field's stored key
reaches you without pretending to be a reference. Fields whose halves are
identical get no companion at all.

The primary key is always a plain string:

.. code-block:: python

   doc.metadata["sys_id"]   # '02a73898...', never a dict or its str()


Turning it off
--------------

Expansion means a fuller metadata dict, and on a wide table that is not a
small difference: a record with 45 reference fields carries roughly three
times as many bytes of metadata once every identifier sits beside its label.

That matters if you write the whole dict into a vector store with a
per-vector metadata limit. Retrieval pipelines that want the small curated
version can ask for it:

.. code-block:: python

   IncidentLoader(conn, expand_references=False)

And anything that needs a field no loader surfaces can keep the whole record:

.. code-block:: python

   doc = IncidentLoader(conn, include_raw=True).load()[0]
   doc.metadata["raw"]["u_custom_field"]

Both apply to every loader, sync and async.


Reading fields yourself
-----------------------

The same helpers the loaders use are public, for code working with
:meth:`SnowConnection.get_records` directly:

.. code-block:: python

   from snowloader import display_value, raw_value, reference, is_sys_id

   for record in conn.get_records("cmdb_ci"):
       display_value(record["sys_class_name"])   # 'MySQL Instance'
       raw_value(record["sys_class_name"])       # 'cmdb_ci_db_mysql_instance'

       ci = reference(record, "assigned_to")
       ci.label     # 'David Loo'
       ci.value     # '6816f79c...'
       str(ci)      # 'David Loo'
       bool(ci)     # False when neither half is populated

       is_sys_id(raw_value(record["cmdb_ci"]))   # True

:func:`snowloader.expand_reference_keys` is the flattening the loaders apply,
available on its own:

.. code-block:: python

   from snowloader import expand_reference_keys

   flat = expand_reference_keys(record)
   flat["assignment_group"]         # label
   flat["assignment_group_sys_id"]  # identifier

Pass ``into=`` to write into a dict you already have. Existing keys are never
overwritten, so your own entries survive.


The class name trap
-------------------

Worth stating on its own, because it is the mistake that costs the most and
gives no sign it happened.

``sys_class_name`` is where ServiceNow records what kind of CI something is.
Its display half is a human label, ``"MySQL Instance"``. Its value half is
the table name, ``"cmdb_ci_db_mysql_instance"``. Code that groups CIs by the
display half files databases under a label that no table is called, and every
count still adds up, so nothing looks wrong.

.. code-block:: python

   # Wrong. Groups by a label.
   ci_type = display_value(record["sys_class_name"])

   # Right. Groups by the table the CI actually lives in.
   ci_type = raw_value(record["sys_class_name"])

   # Or, from a loaded document.
   ci_type = doc.metadata["sys_class_name_value"]

The same reasoning applies to any choice field. ``priority`` reads
``"5 - Planning"`` on the display side and ``"5"`` underneath. Sort or
compare on the label and ``"10 - Something"`` lands before ``"2 - High"``.


Building a graph
----------------

Putting it together, CIs and the edges between them:

.. code-block:: python

   from snowloader import SnowConnection, TableLoader, RelationshipLoader

   conn = SnowConnection(..., display_value="all", order_by="sys_id")

   for doc in TableLoader(conn, table="cmdb_ci").lazy_load(verify=True):
       graph.add_node(
           doc.metadata["sys_id"],
           name=doc.metadata.get("name"),
           ci_class=doc.metadata.get("sys_class_name_value"),
       )

   for doc in RelationshipLoader(conn).lazy_load(verify=True):
       graph.add_edge(
           doc.metadata["parent_sys_id"],
           doc.metadata["child_sys_id"],
           type=doc.metadata["type"],
       )

Both sweeps are verified, both endpoints are identifiers, and nothing needs a
resolution pass afterwards.
