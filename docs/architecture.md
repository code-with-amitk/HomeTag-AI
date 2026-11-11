# System Architecture

## Design overview

- Use Python/FastAPI for REST APIs and server-rendered Jinja2 for public QR pages. 
- PostgreSQL with `pgvector` is the authoritative store for structured records and document embeddings.
- S3 stores original uploads; Redis supports caching and background-job coordination. A worker handles OCR/embedding work and scheduled maintenance checks.

The four named components are logical responsibility boundaries. Start as a modular application and worker unless deployment, scaling, or security requirements justify splitting them into separately deployed services.

## Component responsibilities

| Component | Responsibility | Main dependencies |
|---|---|---|
| `qr-gateway-service` | Public `GET /v1/scan/{tag_id}`, authenticated tag issue/rotation/revocation, field allowlisting, SSR Jinja2 page, cache reads/invalidation | FastAPI, templates, PostgreSQL, Redis; optional CDN (disabled) |
| `inventory-management-service` | Authentication, household membership, property/appliance/technician/service CRUD, upload coordination | FastAPI, Pydantic, PostgreSQL, S3 |
| `ai-rag-service` | Ingestion pipeline, embeddings, hybrid retrieval, grounded response generation | PostgreSQL/pgvector, OCR/LLM providers, S3 |
| `notification-cron-worker` | Due-item evaluation, scheduled notifications, delivery status/retries | PostgreSQL, Redis/worker system, WhatsApp provider |

`app/api/` contains route controllers, `app/services/` contains business logic and integrations, `app/db/` contains persistence models and migrations, and `app/templates/` contains QR SSR templates. Do not put business rules in route handlers.

## Context and data-flow diagram

```mermaid
flowchart LR
    Visitor[Phone camera / visitor] --> Nginx[Nginx Ingress / LoadBalancer]
    Member[Authenticated household member] --> Nginx
    Nginx --> QR[QR gateway / SSR]
    Nginx --> API[Inventory API]
    QR <--> Cache[(Redis cache)]
    QR -->|cache miss| DB[(PostgreSQL + pgvector)]

    API --> DB
    API --> S3[(Private S3 objects)]
    API -->|enqueue upload| Queue[(Redis-backed queue)]
    Queue --> Ingest[Ingestion worker / AI RAG]
    Ingest --> S3
    Ingest --> DB
    API -->|query| RAG[AI RAG retrieval]
    RAG --> DB
    RAG --> LLM[Approved LLM provider]
    LLM --> RAG
    RAG --> API

    Scheduler[Scheduled worker] --> DB
    Scheduler --> WA[Approved WhatsApp provider]
    WA --> Member
```

## Kubernetes deployment boundaries

- **Nginx:** Nginx Ingress Controller exposed by its Kubernetes `LoadBalancer` Service; the application Ingress routes requests to the internal API Service.
- **Web/API runtime:** Two-replica Deployment serving authenticated REST endpoints and public SSR. Public QR lookups must not require user credentials.
- **Worker runtime:** To be added as a separate Deployment when background processing is implemented.
- **PostgreSQL:** One-replica StatefulSet with a PVC for local development; Service is internal to the namespace. This default is not an HA/backup plan for production.
- **Redis:** One-replica internal Deployment used for cache/queue coordination. QR cache contents are non-authoritative and disposable.
- **S3:** Future private object storage; clients access uploads through short-lived, scoped upload/download authorization rather than public object URLs.
- **CDN:** Optional edge cache for public QR pages only after cache-key, privacy, and invalidation behavior are defined.

The local deployment uses ordered `kubectl` manifests under `k8s/`. The API image is built from the root `Dockerfile`; an Alembic Job performs schema migration before API rollout. Secrets are created outside the checked-in manifests. The Nginx Ingress Controller must be installed in the cluster; Docker Desktop already provides it.

## Sequence: public scan

```mermaid
sequenceDiagram
    actor Visitor
    participant Browser as Phone browser
    participant QR as QR gateway
    participant Cache as Redis / optional CDN
    participant DB as PostgreSQL
    Visitor->>Browser: Scan tag
    Browser->>QR: GET /v1/scan/{tag_id}
    QR->>Cache: Lookup public view by tag/version
    alt cache hit
        Cache-->>QR: Allowlisted public view
    else cache miss
        QR->>DB: Resolve active tag and public fields
        DB-->>QR: Public projection only
        QR->>Cache: Cache projection for bounded TTL
    end
    QR-->>Browser: Mobile HTML (< 50 KB)
```

## Sequence: upload, retrieval, and alert

```mermaid
sequenceDiagram
    actor Member
    participant API as Inventory API
    participant S3 as Private object storage
    participant Queue as Background queue
    participant Worker as AI / notification worker
    participant DB as PostgreSQL + pgvector
    participant Provider as LLM / WhatsApp provider
    Member->>API: Upload document (authenticated)
    API->>S3: Store original in private location
    API->>DB: Create document record (pending)
    API->>Queue: Enqueue ingestion job
    Queue->>Worker: Process job
    Worker->>S3: Read authorized object
    Worker->>DB: Store extracted text, chunks, embeddings, status
    Member->>API: Submit inventory question
    API->>DB: Tenant-scoped SQL + vector retrieval
    API->>Provider: Generate grounded response (approved LLM)
    Provider-->>API: Structured answer
    API-->>Member: Answer with source references
    Worker->>DB: Evaluate due maintenance and consent
    Worker->>Provider: Send eligible WhatsApp notification
    Provider-->>Worker: Delivery result
    Worker->>DB: Record outcome and idempotency key
```

## Scalability and resilience

QR reads are read-heavy and may use bounded caching, but PostgreSQL remains the source of truth. Cache invalidation must occur when public fields, tag state, or visibility changes. Background work must be idempotent, retryable, and observable. Provider calls need explicit timeouts and error states; do not silently substitute fabricated results.
