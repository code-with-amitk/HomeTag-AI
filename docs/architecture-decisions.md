# Architecture Decisions and Open Questions

Status legend: **Selected** means the implementation uses this choice for the current phase; it remains revisable at the noted boundary. **Open** means no provider or product decision has been made.


## ADR-002 — Background task framework: Celery vs. ARQ
- Celery with Redis broker for the initial worker foundation.
- SQLAlchemy 2.x with typed mappings. Explicit persistence control and ecosystem maturity; SQLModel for combined Pydantic/ORM ergonomics.

## ADR-004 — LLM provider
- AWS Bedrock, OpenAI, Claude through an approved channel, or another provider meeting privacy and regional requirements.
- Data processing terms, residency, retention/training policy, model quality, structured output, latency, cost, and operational support.

## ADR-005 — WhatsApp provider
- Open; no provider selected.

## ADR-006 — QR caching and CDN
- Selected for the initial public QR gateway; CDN remains disabled.
- Cache only the allowlisted public projection in Redis for 30 seconds and explicitly invalidate it after related writes.

## ADR-007 — Object storage
- AWS S3 storage for original documents and appliance images; database stores metadata and opaque object keys.

## ADR-008 — Subscription and client scope
- Open.

## ADR-009 — Account authentication and household roles
- Selected for the initial inventory API.
- Argon2 password hashes through `pwdlib`, short-lived HS256 bearer access tokens signed with a configured secret, and an owner/member role on household membership records.

## ADR-010 — Kubernetes runtime and Nginx entry point
- Selected for local development and initial deployment structure.
- Run the API, PostgreSQL, and Redis in separate Kubernetes workloads. Expose the API through an Ingress handled by an Nginx Ingress Controller, and keep API/database/cache Services internal. Run Alembic migrations as a Kubernetes Job before API rollout.

