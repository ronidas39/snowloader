:hide-toc:

snowloader
==========

.. raw:: html

   <div class="snow-hero">
     <h1>snowloader</h1>
     <p class="snow-tagline">
       Pull Incidents, Knowledge Base articles, CMDB items, Changes, Problems,
       Catalog items and attachments out of ServiceNow and into LangChain,
       LlamaIndex, or your own pipeline. Every sweep sorts on a unique key, so
       it cannot quietly lose rows, and it can prove it returned everything.
     </p>
     <div class="snow-badges">
       <a href="https://pypi.org/project/snowloader/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/snowloader.svg?label=pypi&amp;color=1a73e8"></a>
       <a href="https://pypi.org/project/snowloader/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/snowloader.svg?label=python&amp;color=4fc3f7"></a>
       <a href="https://snowloader.readthedocs.io"><img alt="Tests" src="https://img.shields.io/badge/tests-389%20passing-10b981.svg"></a>
       <a href="https://github.com/ronidas39/snowloader/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/ronidas39/snowloader/actions/workflows/ci.yml/badge.svg"></a>
       <a href="https://opensource.org/licenses/MIT"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
       <a href="https://peps.python.org/pep-0561/"><img alt="Typed" src="https://img.shields.io/badge/typing-strict-1a73e8.svg"></a>
     </div>
     <div class="snow-cta">
       <a class="snow-cta-primary" href="getting-started.html">Get started</a>
       <a href="cli.html">Command line</a>
       <a href="verification.html">How it verifies</a>
       <a href="api.html">API reference</a>
       <a href="https://github.com/ronidas39/snowloader">Source</a>
     </div>
   </div>

.. code-block:: python

   from snowloader import SnowConnection, IncidentLoader

   with SnowConnection(
       instance_url="https://yourcompany.service-now.com",
       username="api_user",
       password="api_pass",
   ) as conn:
       docs = IncidentLoader(conn, query="active=true").load(verify=True)

Three lines to a list of documents, and ``verify=True`` means the load raises
rather than handing back a quietly incomplete extract.

Or without writing any Python at all:

.. code-block:: bash

   snowloader extract incident --out incidents.jsonl \
       --query "stateIN6,7^close_notesISNOTEMPTY" \
       --display-value all --resume

Run it, kill it, run it again and it continues from where it stopped. It exits
non-zero if the sweep did not return every record, so an unattended job finds
out. See :doc:`cli`.

.. raw:: html

   <div class="snow-stats">
     <div class="snow-stat"><span class="snow-stat-value">9</span><span class="snow-stat-label">loaders, each with an async variant</span></div>
     <div class="snow-stat"><span class="snow-stat-value">4</span><span class="snow-stat-label">pagination paths: sequential, threaded, async, keyset</span></div>
     <div class="snow-stat"><span class="snow-stat-value">4</span><span class="snow-stat-label">authentication modes</span></div>
     <div class="snow-stat"><span class="snow-stat-value">389</span><span class="snow-stat-label">unit tests, plus 21 against a live instance</span></div>
   </div>

The bug this package exists for
-------------------------------

ServiceNow does not guarantee a stable row order inside a group of rows that
tie on the sort column. Every release before 0.3.0 paged over
``sys_created_on``, which is not unique, so a page boundary landing inside a
tied group returned some rows twice and skipped others.

.. raw:: html

   <div class="snow-figure">
     <img alt="A page boundary inside a group of tied rows returns some rows twice and skips others" src="_static/pagination.png">
     <p class="snow-caption">Same eight rows, tied on one timestamp, read four at a time. On the left the
     boundary falls inside the tie. The returned count still reconciles, which is why nothing reported it.</p>
   </div>

The count matched, so nothing raised. The loss was identical on every run, so
re-running never revealed it and comparing two runs showed nothing. Measured on
a developer instance where ``cmdb_ci`` holds 2,919 rows across only 818
distinct timestamps, three consecutive sweeps each returned 2,919 rows of which
only 2,915 were distinct.

:doc:`verification` covers what changed, how to choose your own sort, and how
to make a sweep prove it was complete.

What you get
------------

.. raw:: html

   <div class="snow-grid">
     <div class="snow-card snow-card-alert">
       <span class="snow-kicker">correctness</span>
       <h3>Sweeps that do not lose rows</h3>
       <p>Every paginated read ends its sort on <code>sys_id</code>, so an offset page
       boundary landing inside a tied timestamp cannot silently drop records. Nothing
       in your code has to change to get it.</p>
     </div>
     <div class="snow-card snow-card-alert">
       <span class="snow-kicker">correctness</span>
       <h3>Sweeps that prove it</h3>
       <p><code>verify=True</code> counts the table first and raises
       <code>SweepIncompleteError</code> rather than returning an incomplete extract
       that looks fine. Free on the threaded and async paths.</p>
     </div>
     <div class="snow-card snow-card-alert">
       <span class="snow-kicker">no python needed</span>
       <h3>A command that does it properly</h3>
       <p><code>snowloader extract</code> makes the careful choices the defaults:
       ordering that cannot lose rows, verification on unless switched off, and a
       non-zero exit when a sweep came back short.</p>
     </div>
     <div class="snow-card">
       <span class="snow-kicker">long jobs</span>
       <h3>Resume where it stopped</h3>
       <p>A checkpoint records how far a run reached, so an interrupted sweep of
       half a million records costs you the page it was inside rather than the whole
       job. It repeats rather than drops, by design.</p>
     </div>
     <div class="snow-card">
       <span class="snow-kicker">graph ready</span>
       <h3>Both halves of every field</h3>
       <p>The readable label under the field's own name, and the identifier you join
       on beside it. An incident can reach its CI, its caller and its assignment
       group without you writing the helper.</p>
     </div>
     <div class="snow-card">
       <span class="snow-kicker">coverage</span>
       <h3>Nine loaders, plus any table</h3>
       <p>Incidents, Knowledge Base, CMDB, Changes, Problems, Catalog, Attachments,
       CI relationships, and a generic <code>TableLoader</code> for everything else.
       Each has a matching async variant.</p>
     </div>
     <div class="snow-card">
       <span class="snow-kicker">throughput</span>
       <h3>Four pagination paths</h3>
       <p>Sequential, threaded, async, and a <code>keyset=True</code> cursor that
       survives a restart. The threaded sweep measured about seven times the
       sequential one on a developer instance, and the docs carry the measured
       tables rather than estimates.</p>
     </div>
     <div class="snow-card">
       <span class="snow-kicker">unattended</span>
       <h3>Built for jobs nobody watches</h3>
       <p><code>on_error="skip"</code> finishes past a dead page and then reports what
       it lost. Retry with backoff, rate limiting, per-thread sessions, proxies and
       custom CA bundles.</p>
     </div>
     <div class="snow-card">
       <span class="snow-kicker">integration</span>
       <h3>LangChain and LlamaIndex</h3>
       <p>Thin adapters with no business logic in them, sync and async. The core stays
       framework free, so it drops into your own pipeline just as easily.</p>
     </div>
     <div class="snow-card">
       <span class="snow-kicker">typing</span>
       <h3>Strict types throughout</h3>
       <p>PEP 561 compliant with a <code>py.typed</code> marker, checked under
       <code>mypy --strict</code>, on Python 3.10 through 3.13.</p>
     </div>
   </div>

How it fits together
--------------------

.. raw:: html

   <div class="snow-figure">
     <img alt="snowloader sits between the ServiceNow Table API and your LLM stack" src="_static/architecture.png">
     <p class="snow-caption">The connection layer handles auth, pagination, ordering and retries. Loaders
     normalise each table into a SnowDocument. Adapters translate that for a framework, and carry no logic of their own.</p>
   </div>

Where to go next
----------------

- :doc:`getting-started` installs it and loads the first documents.
- :doc:`verification` is the one to read if you are upgrading from 0.2.x.
- :doc:`references` explains how to get the identifier behind a label, and the
  ``sys_class_name`` trap that silently misfiles records.
- :doc:`concurrent` and :doc:`async` cover the two faster paths and when each
  is the right one.

.. toctree::
   :hidden:
   :caption: User Guide

   getting-started
   cli
   authentication
   loaders
   verification
   references
   resume
   attachments
   concurrent
   async
   adapters
   advanced

.. toctree::
   :hidden:
   :caption: Reference

   configuration
   api
   changelog
   roadmap
