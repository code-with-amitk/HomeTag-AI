# Initial API Contracts

These are implementation-neutral, versioned REST contracts. Request and response bodies are JSON unless noted; implementation schemas must be Pydantic models with explicit `Field(description=...)` metadata. Exact field names and pagination conventions should be kept consistent when implementation begins.

## Conventions

- Prefix authenticated and public API paths with `/v1`.
- Use bearer access tokens for authenticated routes; the QR scan route is intentionally public.
- Use ISO-8601 timestamps in UTC and opaque identifiers. Never use a sequential database key as a public tag secret.
- Return stable error objects: `{"error": {"code": "...", "message": "...", "request_id": "..."}}`.
- Expected statuses: `400` invalid input, `401` missing/invalid authentication, `403` not authorized, `404` absent or inaccessible resource, `409` state conflict, `413` too large, `415` unsupported media type, `422` schema/semantic validation, `429` rate limited, `500/503` server or dependency failure.
- Do not leak whether an inaccessible tenant-owned identifier exists; use the approved not-found policy consistently.

## Endpoint inventory

| Method and path | Auth | Purpose |
|---|---|---|
| `POST /v1/auth/register` | Public | Create an account if self-service registration is enabled |
| `POST /v1/auth/token` | Public | Exchange email/password credentials for a bearer access token |
| `GET /v1/me` | Bearer | Read the authenticated account and household roles |
| `GET /v1/households/{household_id}/members` | Household owner | List household members |
| `POST /v1/households/{household_id}/members` | Household owner | Add an existing account as a member |
| `DELETE /v1/households/{household_id}/members/{member_user_id}` | Household owner | Deactivate a member without deleting their account |
| `GET /v1/scan/{tag_id}` | Public | Render the allowlisted appliance public view as HTML |
| `GET /v1/properties` | Bearer | List properties visible to the member |
| `POST /v1/properties` | Bearer | Create a property |
| `GET /v1/properties/{property_id}` | Bearer | Read a visible property |
| `GET /v1/appliances` | Bearer | List appliances scoped to authorized household/property |
| `POST /v1/appliances` | Bearer | Create an appliance |
| `GET /v1/appliances/{appliance_id}` | Bearer | Read an appliance and permitted related records |
| `PATCH /v1/appliances/{appliance_id}` | Bearer | Update appliance fields and public visibility settings |
| `DELETE /v1/appliances/{appliance_id}` | Bearer | Archive/remove an appliance under retention rules |
| `POST /v1/appliances/{appliance_id}/tags` | Bearer | Create or rotate an opaque QR tag |
| `POST /v1/appliances/{appliance_id}/service-records` | Bearer | Add a service event |
| `POST /v1/appliances/{appliance_id}/documents` | Bearer | Authorize and initiate a document upload |
| `GET /v1/documents/{document_id}` | Bearer | Read document metadata and processing status |
| `DELETE /v1/documents/{document_id}` | Bearer | Request authorized deletion and cleanup |
| `POST /v1/ai/queries` | Bearer | Submit text/transcribed query and return structured grounded results |
| `GET /v1/maintenance` | Bearer | List upcoming/due maintenance items |
| `POST /v1/notification-preferences` | Bearer | Set/update WhatsApp destination and explicit consent |
| `GET /v1/notification-preferences` | Bearer | Read notification preferences |

The initial implementation uses email/password registration and a 30-minute OAuth2 password-form bearer token. Refresh tokens, email verification, and account recovery remain out of scope pending product decisions. Household roles are owner/member; both roles can manage inventory, while only owners can view or manage membership. Property and technician creation requests include a `household_id`, which the API verifies against active membership. API errors use an `error` object containing a stable code, safe message, and request ID; validation errors also include field-level details without echoing submitted values. If uploads use presigned S3 operations, the document-creation response returns a short-lived upload authorization and the client confirms completion before ingestion is queued.

## Implemented Phase 3 routes

| Method and path | Authorization | Purpose |
|---|---|---|
| `POST /v1/auth/register` | Public | Register an account and initial household |
| `POST /v1/auth/token` | Public | Exchange OAuth2 form credentials for a bearer token |
| `GET /v1/me` | Authenticated | Read account and household memberships |
| `GET /v1/households/{household_id}/members` | Household owner | List members |
| `POST /v1/households/{household_id}/members` | Household owner | Add an existing account |
| `DELETE /v1/households/{household_id}/members/{member_user_id}` | Household owner | Deactivate a member |
| `GET /v1/properties` | Authenticated household member | List properties |
| `POST /v1/properties` | Authenticated household member | Create a property |
| `GET /v1/properties/{property_id}` | Property member | Read a property |
| `PATCH /v1/properties/{property_id}` | Property member | Update a property |
| `DELETE /v1/properties/{property_id}` | Property member | Archive a property |
| `GET /v1/appliances` | Authenticated household member | List appliances |
| `POST /v1/appliances` | Property member | Create an appliance |
| `GET /v1/appliances/{appliance_id}` | Appliance member | Read an appliance |
| `PATCH /v1/appliances/{appliance_id}` | Appliance member | Update an appliance |
| `DELETE /v1/appliances/{appliance_id}` | Appliance member | Archive an appliance |
| `GET /v1/technicians?household_id=...` | Household member | List technicians |
| `POST /v1/technicians` | Household member | Create a technician contact |
| `GET /v1/technicians/{technician_id}` | Household member | Read a technician |
| `PATCH /v1/technicians/{technician_id}` | Household member | Update a technician |
| `DELETE /v1/technicians/{technician_id}` | Household member | Deactivate a technician |
| `GET /v1/appliances/{appliance_id}/service-records` | Appliance member | List service history |
| `POST /v1/appliances/{appliance_id}/service-records` | Appliance member | Add a service event |
| `PATCH /v1/service-records/{service_record_id}` | Service-record member | Correct a service event |
| `DELETE /v1/service-records/{service_record_id}` | Service-record member | Delete a service event |

All authenticated endpoints use membership-scoped bearer authorization. Household member listing is owner-only to avoid exposing member email addresses to every household member.

## Implemented Phase 4 QR routes

| Method and path | Authorization | Purpose |
|---|---|---|
| `GET /v1/scan/{tag_id}` | Public | Render the active tag's allowlisted HTML projection |
| `POST /v1/appliances/{appliance_id}/tags` | Appliance member | Create or rotate an opaque tag and explicitly approve public fields |
| `PATCH /v1/tags/{tag_id}` | Tag owner's household member | Replace the public-field allowlist |
| `DELETE /v1/tags/{tag_id}` | Tag owner's household member | Revoke the tag and invalidate its public cache entry |

Tag creation accepts `public_fields`, a list of `name`, `make`, `model`, `warranty_expiry`, `technician_contact`, and `service_history`; the default is an empty list. Creating a tag revokes any currently active tag for the appliance and returns an opaque `tag_id` plus `scan_path`. Technician details appear only when `technician_contact` is approved and an active appliance technician exists. Service entries appear only when `service_history` is approved and each record has `is_public: true`; the page shows at most the 10 most recent events, with descriptions capped at 500 characters. Cost and technician identifiers are never included. Appliance serial numbers and property/address data are never part of the public projection.

Unknown, inactive, archived, and revoked tags all render the same generic HTML 404 page. Valid pages are mobile optimized and contain no external assets. Redis caches only the public projection for 30 seconds; writes that can affect it explicitly invalidate associated tag entries. Scan responses use `Cache-Control: no-store`, and CDN caching is disabled.

## Representative contract shapes

### Public scan

`GET /v1/scan/{tag_id}` returns `text/html` for an active tag. Unknown, revoked, or non-public tags return a generic not-found response/page and must not reveal private appliance data. `tag_id` is an unguessable opaque value; no personal data is embedded in the QR URL.

### Appliance

Create/update fields: `property_id`, `name`, optional `make`, `model`, `serial_number` (private), `purchase_date`, `warranty_expiry`, optional `technician_id`, and maintenance metadata. Public visibility is controlled by an explicit allowlist rather than serializing this full object.

Response: appliance identifier, property identifier, public display fields, private fields only for authorized members, timestamps, and linked service/document summaries according to the caller's permissions.

### Document upload

Request metadata: appliance identifier, original filename, declared content type, size, and document category. The server validates policy before creating a document record. Response includes document identifier, upload method/URL if applicable, expiration, required headers, and `pending_upload` status. Completion transitions into `queued`/`processing`; clients poll the document resource for terminal status.

### AI query

Request: `{"query": "Which appliances need filter replacement in the next 3 months?", "property_id": "...optional..."}`.

Response: structured answer text, typed result items (appliance/maintenance identifiers and relevant dates), source references (document/page or record), and a `limitations`/`needs_clarification` indicator where needed. Results are tenant-scoped, and date filters must be represented as validated query constraints rather than arbitrary generated SQL.

### Notification preference

Request includes a verified/validated destination, enabled channel, explicit consent state, and consent timestamp/source. Responses must not expose the full destination to unrelated household members.

## API documentation requirements

All implemented request/response models require field descriptions and type annotations. FastAPI `/docs` and `/redoc` are enabled for authenticated API exploration in non-production as appropriate; production exposure is a deployment decision. Define pagination, idempotency headers for retryable mutations, and exact error bodies consistently before endpoint implementation.
