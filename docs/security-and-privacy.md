# Security and Privacy Requirements

These are product requirements for design and implementation, not a claim that controls have already been deployed or independently audited.

## Trust boundaries and data classification

- **Public:** Only the per-appliance fields explicitly enabled for anonymous QR display.
- **Household-private:** Property/address data, serial numbers, full technician contacts, service records not marked public, appliance inventory, and household membership.
- **Sensitive uploaded data:** Invoices, receipts, manuals, images, extracted text, and embeddings; treat all as private even when the source document appears innocuous.
- **Credentials/secrets:** Password verifiers, access tokens, provider credentials, signing keys, and storage credentials. Never include these in logs or source control.

## Identity and tenant isolation

- Authenticate all account, household, inventory, document, AI-query, and notification-preference operations.
- Authorize every resource against the caller's active household membership and role; enforce ownership in the query/service layer.
- Reject cross-tenant references even when IDs are supplied in nested request fields.
- The initial identity implementation hashes passwords with Argon2 and issues 30-minute HS256 bearer tokens. Production must configure a unique signing secret; the built-in development-only key is rejected in production.
- Refresh/revocation, email verification, account recovery, and authentication rate limiting remain required production follow-ups.
- Member roles can manage household inventory; only owners can list/add/remove household members. Cross-household resource IDs return a non-disclosing not-found response.
- Rate-limit authentication and public tag endpoints; avoid account/tag enumeration in responses.

## Public QR route

- Use unguessable, revocable tag IDs; do not place user, address, serial, or other personal data in tag IDs/URLs.
- Return a dedicated public projection, never a generic appliance model or ORM serialization.
- Require explicit owner control for exposing contact details and service history.
- Do not serve documents, internal IDs, membership details, or private metadata from the scan endpoint.
- The tag field allowlist is restricted to appliance name, make, model, warranty expiry, technician contact, and service history. Contact data is included only when explicitly selected; service history additionally requires each event's `is_public` flag and is bounded to the 10 most recent events with descriptions capped at 500 characters.
- Keep only the allowlisted public projection in Redis for at most 30 seconds; invalidate it after relevant tag, appliance, service, technician, and property-archive writes. The TTL bounds stale exposure if Redis invalidation fails.
- Send `Cache-Control: no-store` on scan responses. CDN caching is disabled until edge-cache privacy and purge behavior are approved.

## Uploads and AI processing

- Enforce allowlisted file types, size limits, content validation, and safe filenames; do not trust extensions or client MIME headers alone.
- Keep S3 buckets private, encrypt objects in transit and at rest, and use short-lived scoped upload/download authorization.
- Consider malware scanning and quarantine before parsing; isolate parsers and impose resource/time limits.
- Restrict extracted text, chunks, and vectors to the source document's household authorization.
- Minimize data sent to third-party OCR/LLM services; document processor terms, retention, region, and model-training policy.
- Treat retrieved document content as untrusted input. It must not override system instructions, authorize tools, or cause cross-tenant retrieval.
- Provide deletion workflow covering original objects, extracted text, embeddings, caches, and backups according to an approved retention policy.

## Personal data and notifications

- Collect only fields needed for inventory, service, and user-requested alerts. Set retention and deletion policies before launch.
- Require explicit, recorded WhatsApp consent; support opt-out and stop sending promptly after withdrawal.
- Verify destinations and minimize what notification text reveals on lock screens/shared devices.
- Protect provider credentials, redact destinations and user/document content from logs, and restrict access to delivery records.

## Application and operational controls

- Use TLS for network communications and encryption at rest for database, backups, and object storage.
- Store secrets in an approved secret manager/environment injection, rotate credentials, and use least-privilege service identities.
- Validate inputs, parameterize database operations, apply CSRF protections where cookie auth is used, and configure security headers for SSR.
- Log actor/resource/request IDs and security-relevant outcomes while excluding credentials and sensitive payload contents.
- Define backup access controls, restore tests, incident response, vulnerability/dependency updates, and audit-log retention before production.
