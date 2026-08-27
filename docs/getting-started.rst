Getting Started
===============

Installation
------------

Install the core library using ``pip`` or ``uv``:

.. tab:: pip

   .. code-block:: bash

      pip install snowloader

.. tab:: uv

   .. code-block:: bash

      uv add snowloader

To use the LangChain or LlamaIndex adapters, install the corresponding extras:

.. tab:: pip

   .. code-block:: bash

      pip install snowloader[langchain]    # LangChain adapter
      pip install snowloader[llamaindex]   # LlamaIndex adapter
      pip install snowloader[all]          # Both adapters

.. tab:: uv

   .. code-block:: bash

      uv add snowloader[langchain]    # LangChain adapter
      uv add snowloader[llamaindex]   # LlamaIndex adapter
      uv add snowloader[all]          # Both adapters

Requirements
~~~~~~~~~~~~

- Python 3.10 or later
- A ServiceNow instance with REST API access
- A ServiceNow user account with appropriate roles (``itil``, ``knowledge``, or ``admin``)

Connecting to ServiceNow
------------------------

Every interaction with ServiceNow starts with a :class:`~snowloader.SnowConnection`:

.. code-block:: python

   from snowloader import SnowConnection

   conn = SnowConnection(
       instance_url="https://mycompany.service-now.com",
       username="admin",
       password="password",
   )

The connection handles authentication, pagination, retry logic, and rate
limiting. See :doc:`authentication` for all supported auth modes and
:doc:`configuration` for tuning parameters.

Loading Your First Documents
----------------------------

Load incidents and iterate over them:

.. code-block:: python

   from snowloader import SnowConnection, IncidentLoader

   conn = SnowConnection(
       instance_url="https://mycompany.service-now.com",
       username="admin",
       password="password",
   )

   loader = IncidentLoader(connection=conn, query="active=true^priority<=2")

   # Stream documents one at a time (memory efficient)
   for doc in loader.lazy_load():
       print(f"[{doc.metadata['number']}] {doc.page_content[:100]}")

   # Or load everything into a list
   all_docs = loader.load()
   print(f"Loaded {len(all_docs)} incidents")

Each document has two parts:

- ``page_content`` - structured text formatted for LLM consumption
- ``metadata`` - a dict with ``sys_id``, ``number``, ``table``, and every
  other field on the record. Reference fields appear twice: the readable
  label under the field's own name, and the identifier you can join on under
  a ``_sys_id`` companion. See :doc:`references`.

Checking the load was complete
------------------------------

A paginated read can come up short without failing, so any run you are not
watching should say so rather than hand back a quiet gap:

.. code-block:: python

   from snowloader import SweepIncompleteError

   try:
       all_docs = loader.load(verify=True)
   except SweepIncompleteError as exc:
       print(exc.report)
       raise

``verify=True`` counts the table before reading it and raises if the load did
not return that many distinct records. :doc:`verification` explains what it
is guarding against and what it costs.

Using with LangChain
--------------------

.. code-block:: python

   from snowloader import SnowConnection
   from snowloader.adapters.langchain import ServiceNowIncidentLoader

   conn = SnowConnection(
       instance_url="https://mycompany.service-now.com",
       username="admin",
       password="password",
   )

   loader = ServiceNowIncidentLoader(connection=conn, query="active=true")
   docs = loader.load()  # Returns list[langchain_core.documents.Document]

   # Use with any LangChain vector store
   from langchain_community.vectorstores import FAISS
   from langchain_openai import OpenAIEmbeddings

   vectorstore = FAISS.from_documents(docs, OpenAIEmbeddings())

Using with LlamaIndex
---------------------

.. code-block:: python

   from snowloader import SnowConnection
   from snowloader.adapters.llamaindex import ServiceNowIncidentReader

   conn = SnowConnection(
       instance_url="https://mycompany.service-now.com",
       username="admin",
       password="password",
   )

   reader = ServiceNowIncidentReader(connection=conn, query="active=true")
   docs = reader.load_data()  # Returns list[llama_index.core.schema.Document]

   # Use with any LlamaIndex index
   from llama_index.core import VectorStoreIndex

   index = VectorStoreIndex.from_documents(docs)
   query_engine = index.as_query_engine()

Next Steps
----------

- :doc:`authentication` - Learn about all 4 auth modes (Basic, OAuth, Bearer Token)
- :doc:`loaders` - Every loader, with examples
- :doc:`verification` - Why a sweep can quietly lose rows, and how to prove
  yours did not
- :doc:`references` - Getting the sys_id behind a label, and the class name
  trap
- :doc:`advanced` - Delta sync, CMDB relationships, journal entries
- :doc:`configuration` - Tune timeouts, retries, rate limiting, and more
