# ServiceNow Table API Reference
# This is the AUTHORITATIVE reference. Do NOT invent endpoints.

## Base URL
`{instance_url}/api/now/table/{table_name}`

## Authentication
### Basic Auth
Header: `Authorization: Basic base64(username:password)`

### OAuth 2.0
Token endpoint: `{instance_url}/oauth_token.do`
Grant type: password
Body: grant_type, client_id, client_secret, username, password
Response: {"access_token": "...", "expires_in": 1800}
Header: `Authorization: Bearer {access_token}`

## Common Parameters
| Parameter | Description | Example |
|-----------|-------------|---------|
| sysparm_limit | Records per page (max 10000) | 100 |
| sysparm_offset | Pagination offset | 0, 100, 200 |
| sysparm_fields | Comma-separated field list | sys_id,number,short_description |
| sysparm_query | Encoded query | active=true^priority=1 |
| sysparm_display_value | Return display values | true, false, all |

## Query Operators
| Operator | Example |
|----------|---------|
| = | active=true |
| != | state!=6 |
| > | sys_updated_on>2024-01-01 |
| < | priority<3 |
| IN | stateIN1,2,3 |
| STARTSWITH | numberSTARTSWITHINC |
| ^ (AND) | active=true^priority=1 |
| ^OR | priority=1^ORpriority=2 |
| ^ORDERBY | ^ORDERBYsys_created_on |
| ^ORDERBYDESC | ^ORDERBYDESCsys_updated_on |

## Response Format
```json
{
  "result": [
    {
      "sys_id": "abc123",
      "number": "INC0010001",
      "short_description": "Email not working",
      "assigned_to": {
        "display_value": "John Smith",
        "value": "def456"
      }
    }
  ]
}
```
Note: Reference fields return {display_value, value} when sysparm_display_value=all

## Tables Used by snowloader
| Table | Description |
|-------|-------------|
| incident | IT Incidents |
| kb_knowledge | Knowledge Base articles |
| cmdb_ci | CMDB Configuration Items (base) |
| cmdb_ci_server | CMDB Servers |
| cmdb_ci_service | CMDB Services |
| cmdb_rel_ci | CMDB CI Relationships |
| change_request | Change Requests |
| problem | Problems |
| sc_cat_item | Service Catalog Items |
| sys_journal_field | Journal entries (work_notes, comments) |

## Journal Entry Query
Table: sys_journal_field
Query: `element_id={sys_id}^elementINwork_notes,comments`
Fields: value, element, sys_created_on, sys_created_by

## CMDB Relationship Query
Table: cmdb_rel_ci
Outbound: `parent={sys_id}` → fields: child, type
Inbound: `child={sys_id}` → fields: parent, type

## Rate Limits
Default: Varies by instance config. Expect 429 responses.
Handle with exponential backoff + Retry-After header.

## CRITICAL NOTES
1. ALWAYS append ^ORDERBYsys_created_on for consistent pagination
2. Max sysparm_limit is 10000 (default varies by instance)
3. Reference fields without sysparm_display_value return sys_id strings only
4. HTML content in kb_knowledge.text field needs cleaning
5. sys_updated_on format: YYYY-MM-DD HH:MM:SS (UTC)
