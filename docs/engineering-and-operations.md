# Engineering and Operations Baseline

This document describes the implemented Kubernetes development setup and the operational work required before production.

## Code and API standards

- Use Python with FastAPI and type annotations throughout.
- Keep controllers, business logic, persistence, and templates separated under `app/api/`, `app/services/`, `app/db/`, and `app/templates/`.
- Use Pydantic request/response schemas with explicit `Field(description=...)` metadata. Keep external schemas distinct from database models.
- Keep `/docs` and `/redoc` coherent and test that the OpenAPI schema builds.
- Every core module should have the required short architectural blockquote explaining purpose, expected throughput, and key dependencies.
- Add Mermaid diagrams in module documentation when explaining complex routing, database, or ingestion behavior.

## Local development and configuration

The local foundation uses Python 3.10 or newer, PostgreSQL 16 with `pgvector`, and Redis 7. Docker Desktop Kubernetes runs the API, PostgreSQL, and Redis in separate Kubernetes workloads. An Nginx Ingress Controller is the HTTP load-balancing/reverse-proxy entry point; Docker Desktop already includes one. The multi-stage `Dockerfile` installs the app and dependencies in a builder stage, then copies the virtual environment and migration configuration into a clean runtime stage. It includes packaged HTML templates and runs as a non-root user. Manifests in `k8s/` configure Deployments, a PostgreSQL StatefulSet and PersistentVolumeClaim, internal Services, a migration Job, and an Ingress resource. The API reads validated `HOMETAG_` environment variables from Kubernetes ConfigMaps and Secrets. For the local cluster, create `hometag-secrets` with a generated Postgres password and JWT signing key; do not commit Secret manifests or reuse development credentials in production.

```bash
./scripts/deploy-local-k8s.sh
```

The script builds the API image, creates the local Secret only if absent, waits for PostgreSQL and Redis, runs the Alembic migration Job, and rolls out the API and Ingress. The Alembic Job applies schema changes before API rollout; Uvicorn runs in each API Pod. The Ingress resource configures the Nginx Ingress Controller to route and balance requests across the API's internal ClusterIP Service. Docker Desktop exposes its controller Service at localhost; check `kubectl get svc -n ingress-nginx`. Install an Nginx Ingress Controller in other clusters before applying the Ingress resource. The API serves interactive documentation at `/docs` and `/redoc`, liveness at `/health/live`, and dependency readiness at `/health/ready`.

For tests and code-quality tools, a host Python virtual environment remains useful: create it with `python -m venv .venv`, activate it, and install `python -m pip install -e ".[dev]"`. Then run `pytest`, `ruff check .`, `ruff format --check .`, and `mypy app`. Running the API itself does not require that host environment. Run the worker using `celery -A app.worker.celery_app:celery_app worker --loglevel=INFO` once background tasks are implemented.

The checked-in Kubernetes manifests are a development starting point, not a production-ready stateful data platform. They run one PostgreSQL StatefulSet replica and one Redis replica; PostgreSQL uses a PVC, while Redis is disposable cache data. Before production, configure an appropriate storage class, backups/restore, PostgreSQL high availability or a managed database, Redis availability/authentication/TLS, resource sizing, secret-manager integration, network policies, TLS termination, and monitoring. API replicas can be scaled independently (for example, `kubectl scale deployment/hometag-api --replicas=4 -n hometag`); configure HPA and cluster capacity based on measured load. Push the API image to a registry accessible by the target cluster and update the image in `k8s/` for non-local clusters.

The worker can be deployed as its own Kubernetes Deployment when background tasks are implemented. The Nginx Ingress Controller can be installed using its supported Helm chart or deployment method; in a cloud environment its Service can integrate with the cloud load balancer.

External S3, LLM/OCR, and WhatsApp integrations should use documented fakes/mocks in tests or explicitly configured development credentials; tests must not require production secrets. Future configuration groups include object-storage, authentication, provider credentials/model identifiers, worker settings, and allowed origins. Commit example placeholders only; never commit secrets.

## Testing strategy

- **Unit:** Date/warranty/maintenance rules, public-field projection, validation, authorization policy, ingestion state transitions, and idempotency.
- **Integration:** PostgreSQL/pgvector persistence and migrations, Redis cache/queue behavior, private object-storage adapter, and provider adapter contracts.
- **API:** OpenAPI generation, authentication, tenant isolation, error shapes, and public QR privacy boundaries.
- **End-to-end:** Register/manage property and appliance, scan QR, upload/process document, query with citations, and deliver/suppress an alert.
- **Resilience/security:** Unknown/revoked tags, cross-tenant identifiers, malformed/oversized uploads, repeated jobs, provider timeouts, retries, and opt-out races.
- **Performance:** Assert QR HTML payload below 50,000 bytes and local scan responses below one second; establish production latency/throughput targets after product traffic expectations are defined.

Use deterministic fixtures and provider fakes. Public QR API tests assert that private serials, private service events, and unapproved technician contacts are absent; verify tag rotation/revocation and cache invalidation; and measure rendered payload size and response time against the local limits above. Do not send real messages or personal documents in automated tests.

## CI and quality gates

The CI workflow is configured to run Ruff lint/format checks, mypy, pytest, and the initial Alembic migration against PostgreSQL with `pgvector`; Redis and PostgreSQL are provided as CI services. Its integration test checks live dependency readiness and the installed vector extension. OpenAPI generation is verified through API tests. Build and deployment pipelines must not expose secrets in logs. Python 3.10 is the initial tested runtime.

## Deployment and migration

Deploy API and worker as separately scalable processes with private database/Redis/object-storage access. Run schema migrations as a controlled release step with backup/rollback strategy; use backward-compatible migrations where rolling deployment is needed. Separate development, staging, and production credentials and data. Define region, availability, backup cadence, RPO/RTO, and rollback procedure before production launch.

## Observability and operations

- Emit structured logs with timestamp, severity, service, request/job ID, and outcome; redact personal and secret values.
- Track API latency/error rate, QR cache hit ratio and rendered payload size, database health, queue depth/age, ingestion success/failure/latency, LLM latency/error/cost, and notification attempt/delivery/suppression rates.
- Provide liveness/readiness checks without exposing sensitive configuration.
- Alert on sustained service errors, stuck/old jobs, database/storage failures, and provider delivery failures.
- Maintain runbooks for failed ingestion, cache invalidation/tag revocation, queue backlog, provider outage, credential rotation, backup restore, and privacy/security incident response.
- Numeric service-level objectives, alert thresholds, retention, and support ownership require product/operations approval before launch.
