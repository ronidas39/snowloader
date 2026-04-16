Authentication
==============

snowloader supports four authentication modes, listed in recommended order
for production use. The connection auto-detects which mode to use based on
the credentials you provide.

OAuth 2.0 Client Credentials (Recommended)
-------------------------------------------

Best for server-to-server integrations. No user password needed - the OAuth
application is tied to a ServiceNow user whose permissions govern API access.

.. code-block:: python

   conn = SnowConnection(
       instance_url="https://mycompany.service-now.com",
       client_id="your_client_id",
       client_secret="your_client_secret",
   )

**ServiceNow setup:**

1. Navigate to **System OAuth > Application Registry**
2. Click **New** and select *Create an OAuth API endpoint for external clients*
3. Fill in the application name and record the **Client ID** and **Client Secret**
4. The OAuth plugin (``com.snc.platform.security.oauth``) must be active

Tokens are acquired lazily on the first API call and refreshed automatically
when they expire (HTTP 401 triggers re-acquisition).

OAuth 2.0 Password Grant
-------------------------

Pass all four credentials. Suitable when you need user-level access control
and the client is trusted (server-side application, not a browser).

.. code-block:: python

   conn = SnowConnection(
       instance_url="https://mycompany.service-now.com",
       client_id="your_client_id",
       client_secret="your_client_secret",
       username="api_user",
       password="api_password",
   )

Same ServiceNow OAuth setup as client credentials. The difference is that
the token is acquired using the ``password`` grant type with user credentials.

Bearer Token
------------

Pass a pre-obtained token directly. Useful when authentication is handled
outside the library - for example, through SSO, a corporate token service,
or a manually acquired OAuth token.

.. code-block:: python

   conn = SnowConnection(
       instance_url="https://mycompany.service-now.com",
       token="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
   )

When using a bearer token, the connection does not manage token lifecycle.
If the token expires, the API call will fail with a 401 error. You are
responsible for refreshing the token externally.

Basic Auth
----------

The simplest mode. Credentials are sent with every request. Fine for
development and testing, but **not recommended for production** because:

- Credentials are sent on every request (base64-encoded, not encrypted)
- If MFA is enabled on the account, basic auth will fail
- No token expiry or rotation

.. code-block:: python

   conn = SnowConnection(
       instance_url="https://mycompany.service-now.com",
       username="admin",
       password="password",
   )

ServiceNow Roles
----------------

The user account (or the user linked to the OAuth application) needs
appropriate roles to access the tables:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Table
     - Required Role
   * - ``incident``
     - ``itil`` or ``sn_incident_read``
   * - ``kb_knowledge``
     - ``knowledge`` or ``knowledge_manager``
   * - ``cmdb_ci`` / ``cmdb_ci_server`` / etc.
     - ``itil`` or ``cmdb_read``
   * - ``change_request``
     - ``itil`` or ``sn_change_read``
   * - ``problem``
     - ``itil`` or ``sn_problem_read``
   * - ``sc_cat_item``
     - ``catalog`` or ``catalog_admin``

The ``admin`` role grants access to all tables but violates the principle
of least privilege. Create a dedicated integration user with only the roles
needed for your use case.

Proxy and Certificate Support
-----------------------------

For enterprise environments behind a corporate proxy or with custom CA
certificates:

.. code-block:: python

   conn = SnowConnection(
       instance_url="https://mycompany.service-now.com",
       username="admin",
       password="password",
       proxy="http://corporate-proxy:8080",
       verify="/path/to/custom-ca-bundle.pem",
   )

Set ``verify=False`` to disable SSL verification entirely (not recommended
for production).
