# Product Requirements — HomeTag AI

## Product goal

HomeTag AI helps households keep reliable appliance records and act on maintenance needs. The product combines a public, no-download QR scan experience with an authenticated inventory and subscription experience.

## Users and access

- **Owner/member:** Authenticated household member who manages one or more properties and their appliances.
- **Invited household member:** A member with permissions granted by the household; exact roles and permission granularity are an open product decision.
- **Technician/visitor:** Anyone scanning a physical QR code in a standard phone camera. A scan does not require an account or app.
- **Operator:** Internal role responsible for service reliability and support; no end-user administrative console is assumed in the initial scope.

## Product tiers

### Free: QR appliance page

A physical QR tag resolves to a lightweight server-rendered page. It may show only the public fields deliberately enabled for that appliance:

- Make and model.
- Purchase date and warranty expiry, when available.
- Technician contact, when explicitly shared.
- Service history selected for public display.

The page must be mobile-optimized, fast, and usable without account creation or app installation. The complete response payload target is less than 50 KB.

### Paid: household inventory and assistance

- Authenticated management of appliances across multiple properties.
- Household sharing, subject to an approved membership/permission model.
- Upload and search manuals, invoices, receipts, and service records.
- Text search using natural-language questions over structured appliance data and relevant documents.
- Voice-to-text input where supported by the selected client and transcription approach.
- Proactive maintenance and warranty notifications through an approved WhatsApp provider.

## Core workflows

1. **Register and manage an appliance:** An owner creates a household/property and records appliance details, dates, technician information, service events, and maintenance schedule.
2. **Create and use a QR tag:** An owner associates an opaque tag identifier with an appliance and prints/places its QR code. A visitor scans it and sees the approved public view.
3. **Upload a document:** An authorized household member uploads a supported file, associates it with an appliance, and sees processing status.
4. **Ask an inventory question:** A member submits text (or a transcript from voice input); the system combines constrained structured filters and document retrieval and returns a grounded, structured answer.
5. **Receive a maintenance alert:** A scheduled worker finds an eligible due item, checks user consent and delivery eligibility, sends a WhatsApp message, and records the outcome.

## Initial functional requirements

- The API distinguishes public tag lookups from authenticated household operations.
- Every household-owned resource is scoped to the requesting member's authorized household; cross-household access is denied.
- Owners can create, read, update, and archive appliances and maintain service history and technician records.
- Public QR data is explicitly allowlisted; private household and document data is never exposed by the scan route.
- Document ingestion is asynchronous and reports pending, processing, completed, or failed status.
- AI answers return structured results and references to the records/documents used; unsupported or ungrounded conclusions are not presented as facts.
- Notification delivery respects consent and records enough state to avoid duplicate sends and investigate failures.

## MVP boundaries

The initial product target is a single deployable backend with clearly separated QR, inventory, AI, and worker modules. The service names in the blueprint describe responsibility boundaries; independently deployed microservices are not required for the first release.

Included: appliance and property inventory, public QR page, document ingestion, text-based hybrid search, and maintenance/warranty alerts after provider approval.

Not assumed for MVP: native mobile apps, appliance telemetry/IoT integrations, payments/subscription billing implementation, technician dispatch/booking, public document downloads, arbitrary public profile pages, or autonomous changes to appliance records.

## Acceptance criteria and quality goals

- Public QR page works in a standard mobile browser with no login and returns under 50 KB for the page payload.
- Public route exposes only approved fields and safely handles unknown, disabled, or revoked tags.
- Authenticated resource access is tenant-scoped and covered by automated authorization tests.
- OpenAPI schemas are Pydantic-based, include field descriptions, and are served through FastAPI `/docs` and `/redoc`.
- Core services, failure behavior, provider integrations, and data flows are testable without live external accounts.
- Performance, availability, retention, recovery-time, and recovery-point objectives must be set before production launch; the blueprint does not specify numeric targets for these.
