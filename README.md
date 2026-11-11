# HomeTag AI

HomeTag AI is a hybrid home-appliance inventory and maintenance platform. Its free QR experience gives a user or technician a fast, no-app appliance information page. Its authenticated subscription experience manages appliances across properties and adds document-powered search and proactive maintenance alerts.

## Project documentation

- [Product requirements](./docs/product-requirements.md) — users, workflows, scope, and acceptance criteria.
- [System architecture](./docs/architecture.md) — services, responsibilities, boundaries, and end-to-end flows.
- [API contracts](./docs/api-contracts.md) — initial REST endpoint and error conventions.
- [Data model](./docs/data-model.md) — entities, tenant ownership, and Mermaid ERD.
- [Architecture decisions](./docs/architecture-decisions.md) — recorded decisions, proposals, and open approvals.
- [Security and privacy](./docs/security-and-privacy.md) — trust boundaries and baseline controls.
- [AI ingestion and notifications](./docs/ai-ingestion-and-notifications.md) — document processing, RAG search, and maintenance alerts.
- [Engineering and operations](./docs/engineering-and-operations.md) — local setup expectations, testing, deployment, and monitoring.
- [Phased action plan](./todolist.md) — phase-by-phase deliverables and completion status.

## Kubernetes development environment

The initial backend uses Python/FastAPI, SQLAlchemy, PostgreSQL with `pgvector`, Redis, and Celery. Account passwords are Argon2-hashed, bearer tokens are short-lived, and inventory APIs enforce household membership. LLM, WhatsApp, billing, and client-platform choices remain open; see [architecture decisions](./docs/architecture-decisions.md).

Run the API, PostgreSQL, and Redis as separate Kubernetes workloads. An Nginx Ingress Controller provides the public load-balancing/reverse-proxy entry point; the API, database, and cache are internal cluster services. Docker Desktop Kubernetes is the intended local cluster and already includes an Nginx Ingress Controller.

```bash
./scripts/deploy-local-k8s.sh
```

The script builds the runtime image, applies the namespace, creates `hometag-secrets` only if it does not already exist, waits for PostgreSQL and Redis, runs migrations, then deploys and waits for the API. It preserves the existing Secret on repeat runs so it will not unexpectedly change the database password or invalidate tokens. For a fresh cluster, it generates local credentials automatically. To supply credentials explicitly on first deployment, set `HOMETAG_POSTGRES_PASSWORD` and `HOMETAG_JWT_SECRET_KEY` before running it. Do not commit these values or use development credentials in production.

The sequence above starts the database and cache first, waits for them, runs the migration Job, and only then creates the API deployment and Ingress. The Ingress routes through the installed Nginx controller's LoadBalancer Service; on Docker Desktop the URL is usually `http://localhost`. Open `/docs` or `/redoc`, and check readiness at `/health/ready`. Use `kubectl get svc -n ingress-nginx` to inspect the controller's external address. If the controller is not installed, install an Nginx Ingress Controller before applying `k8s/ingress.yaml`.

Run `./scripts/deploy-local-k8s.sh` again for application updates or new migrations. PostgreSQL data is stored in a PersistentVolumeClaim. `kubectl delete namespace hometag` removes the workloads and namespace; inspect/delete its PersistentVolumeClaim separately if you also intend to remove the database data.

The [Dockerfile](./Dockerfile) uses a multi-stage build: the builder stage creates an isolated Python environment and installs the application and dependencies; the runtime stage copies only that environment and the Alembic migration files/configuration. It starts Uvicorn bound to `0.0.0.0:8000` as a non-root user. HTML templates are included in the installed application package. The [k8s/](./k8s/) manifests describe Kubernetes Deployments/StatefulSet, internal Services, storage, configuration, migration Job, and Nginx Ingress routing. The Ingress Controller distributes traffic to the API's ClusterIP Service; clients do not connect directly to a Pod IP.

For code-quality checks on the host, create a Python environment and install development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
mypy app
```

The host virtual environment is for developer tools and tests; it is not required to serve the API. To stop this application stack, run `kubectl delete namespace hometag`. This removes the namespace's workloads; inspect/delete its PersistentVolumeClaim separately if you also intend to remove the database.

## Test the public QR flow

Start the Kubernetes workloads as above. Set `BASE_URL` to the Nginx Ingress Controller address (typically `http://localhost` on Docker Desktop). In another terminal, register an owner and save the returned household ID. Use a fresh email address each time you repeat this flow.

```bash
BASE_URL=http://127.0.0.1
curl -sS "$BASE_URL/v1/auth/register" \
  -H 'Content-Type: application/json' \
  -d '{"email":"qr-owner@example.com","password":"correct horse battery staple","household_name":"QR home"}'
```

Log in and use the access token from the response for inventory and QR-tag management:

```bash
TOKEN=$(curl -sS "$BASE_URL/v1/auth/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'username=qr-owner@example.com' \
  --data-urlencode 'password=correct horse battery staple' | jq -r .access_token)
HOUSEHOLD_ID='<household id from registration>'

PROPERTY_ID=$(curl -sS "$BASE_URL/v1/properties" \
  -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"household_id\":\"$HOUSEHOLD_ID\",\"name\":\"QR test home\"}" | jq -r .id)
APPLIANCE_ID=$(curl -sS "$BASE_URL/v1/appliances" \
  -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"property_id\":\"$PROPERTY_ID\",\"name\":\"Water purifier\",\"make\":\"Acme\",\"model\":\"Clear 2\",\"warranty_expiry\":\"2030-01-01\"}" | jq -r .id)
TECHNICIAN_ID=$(curl -sS "$BASE_URL/v1/technicians" \
  -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"household_id\":\"$HOUSEHOLD_ID\",\"name\":\"Repair Team\",\"phone\":\"+1-555-0101\"}" | jq -r .id)
curl -sS "$BASE_URL/v1/appliances/$APPLIANCE_ID/service-records" \
  -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"serviced_at\":\"2025-03-01\",\"description\":\"Filter replaced\",\"technician_id\":\"$TECHNICIAN_ID\",\"is_public\":true}"
TAG=$(curl -sS "$BASE_URL/v1/appliances/$APPLIANCE_ID/tags" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"public_fields":["name","make","model","warranty_expiry","technician_contact","service_history"]}')
echo "$TAG"
```

Open the returned `scan_path` (for example, `http://localhost/v1/scan/<tag_id>`) in a private browser window. To test with a phone, the Nginx controller must have a LAN-reachable address; Docker Desktop commonly exposes it only on localhost. Only the tag's selected allowlist is shown; service entries also require `"is_public": true`. Add `"technician_contact"` to the tag allowlist only when the owner wants the linked active technician's contact details exposed. Repeating the tag-creation request rotates the tag and revokes the previous URL. Revoke a current tag with `DELETE /v1/tags/{tag_id}`.

Unknown and revoked URLs return the same generic 404 HTML page. The page shows at most 10 public service events, with descriptions capped at 500 characters, to keep its rendered size bounded. The Redis projection cache expires after 30 seconds and is explicitly invalidated by tag, appliance, service-history, technician, and property-archive changes. Scan responses use `Cache-Control: no-store`; no CDN cache is enabled.
