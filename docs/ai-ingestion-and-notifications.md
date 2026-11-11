# Document Ingestion, RAG, and Maintenance Notifications

## Document lifecycle

1. An authenticated member submits document metadata for an appliance and requests upload authorization.
2. The API verifies household membership, appliance ownership, file limits, and allowed content type; it creates a `pending_upload` record.
3. The original is uploaded to a private S3 location. The client confirms completion; the API verifies object metadata and queues an idempotent job.
4. A worker marks the document `processing`, fetches the authorized object, validates/scans it, and extracts text using the approved OCR/parser.
5. Normalize text, retain page/source metadata, split into bounded chunks, create embeddings with a recorded model/version, and persist chunks/vectors in PostgreSQL/pgvector.
6. Mark the document `completed`, or set a meaningful `failed` state and error category. Retry transient errors with bounded backoff; do not retry permanent unsupported/corrupt-file errors indefinitely.
7. Expose status to authorized household members. Support safe deletion/reprocessing across S3 and database data under the approved retention policy.

Every job carries a document identifier and idempotency key, not client-supplied tenant authority. The worker rechecks document state and ownership before accessing data. Duplicate enqueue/delivery must not create duplicate chunks or inconsistent state.

## Query and retrieval flow

1. Authenticate the member and resolve authorized household/property scope.
2. Accept text or a client-produced voice transcript. Voice capture/transcription provider and data policy require separate approval.
3. Parse intent into a constrained, typed set of supported filters (for example maintenance type and due-date window); never execute model-generated SQL.
4. Run tenant-scoped structured SQL filters and vector similarity retrieval over only the member's permitted documents.
5. Supply a minimal, relevant context to the approved LLM and request a typed response.
6. Validate response shape, attach source identifiers/page references, and return limitations or clarification needs. If retrieval is empty or generation fails, report that explicitly rather than inventing an answer.

Evaluate retrieval relevance, answer grounding, cross-tenant isolation, prompt injection resistance, latency, and cost using a representative, privacy-safe test set before production.

## Maintenance rules

- A schedule has an explicit appliance, rule/type, due date or interval, enabled state, and optional source.
- Evaluate enabled schedules on a configurable cadence and define alert windows (for example, due soon, due today, overdue) from product-approved rules.
- Compute due state deterministically from stored dates/rules; use the LLM only for optional language, never as the authority for whether an alert is due.
- Check current household membership/preferences and recorded consent immediately before sending.
- Use a unique idempotency key per schedule, recipient, and alert window to prevent duplicates.
- Record queued, attempted, sent/delivered, failed, and suppressed/opted-out outcomes; provider webhooks may update delivery state.
- Retry transient provider errors with bounded backoff; avoid retrying permanent policy/recipient errors without correction.
- Provide a way to disable schedules and notifications and honor opt-out promptly.

Exact lead times, message templates, quiet hours, timezone rules, retry limits, and retention are product decisions to approve before implementation.
