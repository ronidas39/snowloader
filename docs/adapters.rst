Framework Adapters
==================

snowloader's core loaders produce framework-agnostic ``SnowDocument``
objects. The adapter layer converts these into the document types that
LangChain and LlamaIndex expect, with zero business logic - all the real
work happens in the core loaders.

LangChain
---------

The LangChain adapters implement ``langchain_core.document_loaders.BaseLoader``,
so they work with any LangChain vector store, retriever, or chain.

.. code-block:: bash

   pip install snowloader[langchain]

**Available adapters:**

- ``ServiceNowIncidentLoader``
- ``ServiceNowKBLoader``
- ``ServiceNowCMDBLoader``
- ``ServiceNowChangeLoader``
- ``ServiceNowProblemLoader``
- ``ServiceNowCatalogLoader``

**Usage:**

.. code-block:: python

   from snowloader import SnowConnection
   from snowloader.adapters.langchain import ServiceNowIncidentLoader

   conn = SnowConnection(instance_url="...", username="...", password="...")

   loader = ServiceNowIncidentLoader(connection=conn, query="active=true")

   # load() returns list[langchain_core.documents.Document]
   docs = loader.load()

   # lazy_load() yields one Document at a time
   for doc in loader.lazy_load():
       print(doc.page_content[:100])

   # Delta sync
   from datetime import datetime, timezone
   updated = loader.load_since(datetime(2024, 1, 1, tzinfo=timezone.utc))

**RAG pipeline example:**

.. code-block:: python

   from langchain_community.vectorstores import FAISS
   from langchain_openai import OpenAIEmbeddings

   docs = ServiceNowIncidentLoader(connection=conn).load()
   vectorstore = FAISS.from_documents(docs, OpenAIEmbeddings())
   retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

All loader parameters (``query``, ``fields``, ``include_journals``,
``ci_class``, ``include_relationships``, etc.) are passed through to
the underlying core loader via ``**kwargs``.

LlamaIndex
----------

The LlamaIndex adapters implement ``llama_index.core.readers.base.BaseReader``,
so they work with any LlamaIndex index.

.. code-block:: bash

   pip install snowloader[llamaindex]

**Available readers:**

- ``ServiceNowIncidentReader``
- ``ServiceNowKBReader``
- ``ServiceNowCMDBReader``
- ``ServiceNowChangeReader``
- ``ServiceNowProblemReader``
- ``ServiceNowCatalogReader``

**Usage:**

.. code-block:: python

   from snowloader import SnowConnection
   from snowloader.adapters.llamaindex import ServiceNowIncidentReader

   conn = SnowConnection(instance_url="...", username="...", password="...")

   reader = ServiceNowIncidentReader(connection=conn, query="active=true")

   # load_data() returns list[llama_index.core.schema.Document]
   docs = reader.load_data()

   # Delta sync
   from datetime import datetime, timezone
   updated = reader.load_data_since(datetime(2024, 1, 1, tzinfo=timezone.utc))

**Metadata exclusion:**

By default, ``sys_id`` is excluded from LLM metadata (it is still available
in the metadata dict, but marked so embedding models and LLMs skip it).
You can customize this:

.. code-block:: python

   reader = ServiceNowIncidentReader(
       connection=conn,
       excluded_llm_metadata_keys=["sys_id", "sys_created_on", "sys_updated_on"],
   )

**RAG pipeline example:**

.. code-block:: python

   from llama_index.core import VectorStoreIndex

   docs = ServiceNowIncidentReader(connection=conn).load_data()
   index = VectorStoreIndex.from_documents(docs)
   query_engine = index.as_query_engine()
   response = query_engine.query("What incidents are related to email?")
