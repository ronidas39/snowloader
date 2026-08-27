Configuration Reference
=======================

SnowConnection Parameters
-------------------------

.. list-table::
   :header-rows: 1
   :widths: 22 12 10 56

   * - Parameter
     - Type
     - Default
     - Description
   * - ``instance_url``
     - ``str``
     - *required*
     - Full URL of your ServiceNow instance (e.g. ``https://mycompany.service-now.com``).
   * - ``username``
     - ``str``
     - ``None``
     - ServiceNow username. Required for basic auth and OAuth password grant.
   * - ``password``
     - ``str``
     - ``None``
     - ServiceNow password.
   * - ``client_id``
     - ``str``
     - ``None``
     - OAuth client ID. Enables OAuth when combined with ``client_secret``.
   * - ``client_secret``
     - ``str``
     - ``None``
     - OAuth client secret.
   * - ``token``
     - ``str``
     - ``None``
     - Pre-obtained bearer token. When set, all other credentials are ignored.
   * - ``page_size``
     - ``int``
     - ``100``
     - Records per API call (1-10,000). Larger values reduce the number of HTTP calls but increase memory per page.
   * - ``timeout``
     - ``int``
     - ``60``
     - HTTP request timeout in seconds. Increase for slow instances or large payloads.
   * - ``max_retries``
     - ``int``
     - ``3``
     - Maximum retry attempts for transient failures (429, 502, 503, 504).
   * - ``retry_backoff``
     - ``float``
     - ``1.0``
     - Base delay (seconds) between retries. Doubles on each attempt (exponential backoff).
   * - ``request_delay``
     - ``float``
     - ``0.0``
     - Minimum seconds between consecutive API requests. Set to ``0.1`` for ~600 req/min pacing.
   * - ``display_value``
     - ``str``
     - ``"true"``
     - Controls ``sysparm_display_value``. ``"true"`` returns human-readable labels. ``"false"`` returns raw values. ``"all"`` returns both in ``{display_value, value}`` dicts.
   * - ``order_by``
     - ``str | list[str] | None``
     - ``"sys_created_on"``
     - Column, or columns, every paginated read sorts by. ``sys_id`` is appended as a unique tiebreak unless the chain already sorts on it, because offset pagination over a non-unique column loses records. Accepts a ready-made clause such as ``"ORDERBYDESCsys_created_on"``. ``None`` sends no ORDERBY at all. An empty string or empty list is refused. See :doc:`verification`.
   * - ``since_field``
     - ``str``
     - ``"sys_updated_on"``
     - Column a delta sync compares its cutoff against. Set it to ``"sys_created_on"`` on an append-only table, or where the update column is not indexed.
   * - ``proxy``
     - ``str``
     - ``None``
     - Proxy URL (e.g. ``http://proxy:8080``). Applied to all HTTP and HTTPS requests.
   * - ``verify``
     - ``bool | str``
     - ``True``
     - SSL verification. ``True`` uses system CA bundle. Pass a file path for custom CA certificates. ``False`` disables verification.

Loader Common Parameters
------------------------

All loaders accept these parameters (inherited from ``BaseSnowLoader``):

.. list-table::
   :header-rows: 1
   :widths: 22 12 10 56

   * - Parameter
     - Type
     - Default
     - Description
   * - ``connection``
     - ``SnowConnection``
     - *required*
     - An initialized connection instance.
   * - ``query``
     - ``str``
     - ``None``
     - ServiceNow encoded query string for filtering records.
   * - ``fields``
     - ``list[str]``
     - ``None``
     - Specific fields to request. ``None`` returns all fields.
   * - ``include_journals``
     - ``bool``
     - ``False``
     - Fetch and append work notes/comments from ``sys_journal_field``.
   * - ``expand_references``
     - ``bool``
     - ``True``
     - Surface every field on the record in metadata, with a companion key holding the second half of any field whose halves differ. ``False`` restores the curated-only metadata from 0.2.x. See :doc:`references`.
   * - ``include_raw``
     - ``bool``
     - ``False``
     - Attach the untouched API record under ``metadata["raw"]``.

Read Method Parameters
----------------------

``load``, ``lazy_load``, ``concurrent_load``, ``concurrent_lazy_load``,
``aload`` and ``alazy_load`` all take these, as do
``SnowConnection.get_records``, ``concurrent_get_records`` and
``AsyncSnowConnection.aget_records``:

.. list-table::
   :header-rows: 1
   :widths: 22 12 10 56

   * - Parameter
     - Type
     - Default
     - Description
   * - ``verify``
     - ``bool``
     - ``False``
     - Count the table before reading it and raise ``SweepIncompleteError`` if the sweep did not return that many distinct records. Costs one extra request on the sequential path and nothing on the threaded and async paths. Holds one key per record, which is why it is opt-in. See :doc:`verification`.
   * - ``on_error``
     - ``str``
     - ``"raise"``
     - What to do when a page cannot be fetched after its retries are exhausted. ``"raise"`` aborts the sweep. ``"skip"`` logs it at ERROR, leaves a gap and lets the rest finish.

CMDBLoader Extra Parameters
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 12 10 50

   * - Parameter
     - Type
     - Default
     - Description
   * - ``ci_class``
     - ``str``
     - ``"cmdb_ci"``
     - CMDB class table to query. Use ``"cmdb_ci_server"``, ``"cmdb_ci_service"``, etc.
   * - ``include_relationships``
     - ``bool``
     - ``False``
     - Traverse the relationship graph via ``cmdb_rel_ci``. Adds 2 API calls per CI.
   * - ``max_relationship_workers``
     - ``int``
     - ``2``
     - Number of concurrent threads for relationship queries.

LlamaIndex Adapter Extra Parameters
------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 32 12 16 40

   * - Parameter
     - Type
     - Default
     - Description
   * - ``excluded_llm_metadata_keys``
     - ``list[str]``
     - ``["sys_id"]``
     - Metadata keys to exclude from LLM processing. These remain in the metadata dict but are marked so embedding models and LLMs skip them.

Environment Variables
---------------------

snowloader does not read environment variables directly. However, the
example scripts in ``examples/`` use these conventions:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Variable
     - Description
   * - ``SNOW_INSTANCE``
     - ServiceNow instance URL
   * - ``SNOW_USER``
     - ServiceNow username
   * - ``SNOW_PASS``
     - ServiceNow password
