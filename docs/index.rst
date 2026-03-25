snowloader
==========

*by* **Roni Das**

|pypi| |python| |license|

.. |pypi| image:: https://img.shields.io/pypi/v/snowloader.svg
   :target: https://pypi.org/project/snowloader/

.. |python| image:: https://img.shields.io/pypi/pyversions/snowloader.svg
   :target: https://pypi.org/project/snowloader/

.. |license| image:: https://img.shields.io/badge/License-MIT-blue.svg
   :target: https://opensource.org/licenses/MIT

**Comprehensive ServiceNow data loader for AI/LLM pipelines.**

snowloader pulls data from ServiceNow — Incidents, Knowledge Base, CMDB,
Changes, Problems, and Service Catalog — and converts it into document
formats that LangChain, LlamaIndex, and other LLM frameworks consume
directly. Built for production use with proper pagination, delta sync,
retry logic, and memory-efficient streaming.

.. code-block:: python

   from snowloader import SnowConnection, IncidentLoader

   conn = SnowConnection(
       instance_url="https://mycompany.service-now.com",
       username="admin",
       password="password",
   )

   loader = IncidentLoader(connection=conn, query="active=true")
   for doc in loader.lazy_load():
       print(doc.page_content[:200])

Key features:

- **6 loaders** for core ServiceNow tables
- **CMDB relationship traversal** with concurrent graph walking
- **Delta sync** — only fetch records updated since your last sync
- **4 authentication modes** — Basic, OAuth Password, OAuth Client Credentials, Bearer Token
- **LangChain & LlamaIndex adapters** with zero business logic
- **Production-grade** — retry with backoff, rate limiting, thread safety, proxy support
- **Fully typed** — PEP 561 compliant with ``py.typed`` marker

Created by **Roni Das** · `GitHub <https://github.com/ronidas39>`_ · `PyPI <https://pypi.org/project/snowloader/>`_

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   getting-started
   authentication
   loaders
   adapters
   advanced

.. toctree::
   :maxdepth: 2
   :caption: Reference

   configuration
   api
   changelog
   roadmap
