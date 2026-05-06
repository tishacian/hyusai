% papAI / Agentium — Hosting & Compliance (OVHcloud)
% Datategy SAS
% April 2026

# Enterprise SaaS on EU infrastructure

**Audience:** Security, Compliance, DPO (video call)

**Reference:** `ANDRITZ-pack/00_synthese/fiche-hosting-ovh-andritz.docx` (ISO/IEC 27001:2022–aligned full note)

# Agenda

- Executive: what we propose and why it matters
- Architecture & operations (OVHcloud MKS + Datategy platform)
- AI security (local inference on the same cluster)
- Assurance stack (OVHcloud + Datategy)
- GDPR & ISO 27001:2022 mapping (high level)
- Deliverable pack & next steps

# Executive summary

- **SaaS offer:** papAI / Agentium runs as a **containerised platform** on **OVHcloud Managed Kubernetes (MKS)** in **EU data centres (France)** — suitable for enterprise procurement and internal assurance.
- **Compliance narrative:** structured against **ISO/IEC 27001:2022** (Annex A) with a **clear shared-responsibility model** between **OVHcloud** (infrastructure), **Datategy** (platform & security operations), and **you** (business data, accounts, policies).
- **Trust basis:** **OVHcloud** publishes a broad **public compliance catalogue** (ISO 27001 / 27017 / 27018 / 27701, HDS, SecNumCloud, SOC, PCI-DSS, etc.); **Datategy** provides **PAS, BCP, DR, privacy, DPA, SLA, training** in the delivery pack.

# What this deck is (and is not)

- **Is:** A **30–45 minute** Visio-friendly **executive + operational** walkthrough of the hosting note — enough for a first gate with security / legal.
- **Is not:** A substitute for reading the **Word note** during due diligence; the note contains the **detailed control mapping** and evidence pointers.
- **Deliverable:** The same content is bundled in **`ANDRITZ-pack/`** (synthesis `.docx`, Datategy PDFs, archived OVHcloud public pages as PDFs).

# SaaS value for your organisation

| Dimension | What you get |
|-----------|----------------|
| **Sovereignty & residency** | Workloads and data in **EU (FR)** by default; EU legal framework for the hosting chain. |
| **Operational burden** | **Managed Kubernetes control plane** from OVHcloud; Datategy operates the **application plane** (releases, monitoring, backups). |
| **Security transparency** | **Written policies** (Datategy) + **public OVHcloud compliance** pages archived in the pack. |
| **AI governance** | **LLM and embedding inference on-cluster** — prompts, completions, and vectors stay **inside your tenancy boundary** in the standard configuration. |
| **Contract path** | **Art. 28 GDPR** processor role for Datategy; sub-processor documentation for OVHcloud in the public materials pack. |

# Shared responsibility (one slide)

| Layer | Who runs it | What they prove |
|-------|-------------|-------------------|
| **Physical DC, power, cooling, low-level network** | OVHcloud | ISO 27001 family, HDS, SecNumCloud (where applicable), SOC programme, etc. |
| **Kubernetes control plane (MKS)** | OVHcloud | Same compliance catalogue + product SLAs in public terms |
| **Platform workloads** (ingress, mesh, app, data, secrets, **local AI services**) | Datategy | PAS, PCA/PRS, secure SDLC, monitoring, incident process |
| **Tenant content & access policy** | Customer | Data classification, IAM policy, acceptable use, SSO integration |

# Target hosting footprint (operational)

- **Region:** OVHcloud **France** (e.g. GRA / SBG / RBX) — **data at rest in the EU**
- **Orchestration:** **OVH Managed Kubernetes Service (MKS)**
- **Storage:** **Cinder CSI** (`csi-cinder-high-speed`) for persistent volumes
- **Ingress & TLS:** **Istio** + **cert-manager** (TLS 1.2 / 1.3)
- **Identity:** **Keycloak 26** (OIDC); **federation to your IdP** (SAML/OIDC) supported
- **Secrets:** **HashiCorp Vault** in-cluster
- **Data plane:** **PostgreSQL**, **MinIO** (object storage on cluster PV), message bus and time-series as deployed per environment

# Application path (simplified)

1. **Internet** → HTTPS termination at the edge (OVH load balancer)
2. **Istio ingress gateway** → **mTLS** inside the mesh where configured
3. **Web UI + API + IdP** (frontend, FastAPI core, Keycloak)
4. **Optional local AI services** (see next slides) → same namespace / network policies as the app
5. **Encrypted PVs** on Cinder → **snapshot / backup** policy per Datategy PAS

*Full diagram in the Word note.*

# AI layer — designed for enterprise trust

- **LLM inference (LLMaaS):** **vLLM** (or **llama.cpp** for quantised models) as a **private, in-cluster** OpenAI-compatible endpoint — **not** exposed to the public Internet by default
- **Embeddings (EMBaaS):** self-hosted embedding service (e.g. **TEI** / vLLM-embed) with **open models** (e.g. BGE family) on **your** GPU/CPU pool
- **Auxiliary NLP:** semantic / NLI models (e.g. LaBSE, XLM-R) run **locally** via Transformers where needed
- **Supply chain:** model artefacts from **internal registry / object storage** — **no hot pull from the public Internet** in production configuration

# AI — data stays in the tenancy (default posture)

| Risk area | Mitigation |
|-----------|------------|
| **Prompt / completion exfiltration** | Traffic stays **in-cluster**; **NetworkPolicies** restrict who can call LLMaaS/EMBaaS |
| **Shadow IT LLM APIs** | Standard build **does not** route application data to **external** inference providers |
| **Cross-tenant leakage** | **No customer fine-tuning** on your data without explicit agreement + tenant isolation |
| **Observability vs. privacy** | **Metrics** (latency, tokens, status) — **not** bulk export of prompt contents |

# OVHcloud — assurance (public catalogue)

- **ISO/IEC 27001 / 27017 / 27018** — ISMS for cloud services & protection of PII in public cloud
- **ISO/IEC 27701** — privacy information management (PIMS) extension aligned with GDPR thinking
- **HDS** — health data hosting (where the workload requires it)
- **SecNumCloud** — French **ANSSI** trusted cloud qualification (specific offers)
- **SOC 1 / 2 / 3**, **PCI-DSS**, **C5**, **HIPAA** (US DCs where relevant), **CISPE** membership

*Archived PDF snapshots of the public pages are in `ANDRITZ-pack/02_ovhcloud/`.*

# Datategy — ISMS posture (transparent)

- Datategy is **not ISO 27001–certified** as a company today — we state this clearly.
- We operate an **ISMS aligned with ISO/IEC 27001** with a **confidential internal IS policy** and a **communicable Security Assurance Plan (PAS)** in the pack.
- **Organisational controls:** risk management (EBIOS-style), HR security, vendor governance, incident management, annual IS policy review.
- **Technical & SDLC controls:** dependency & container scanning, secure coding (OWASP), change management via GitOps, **annual third-party pentest**, backup & restore testing.

# GDPR — roles (who is controller / processor)

| Role | Party |
|------|--------|
| **Controller** | Your organisation — defines purposes and means for personal data you place in the service |
| **Processor** | **Datategy SAS** — builds and operates papAI / Agentium for you |
| **Sub-processor (hosting)** | **OVHcloud (OVH SAS)** — EU data centres, public compliance materials in the pack |

**Default residency:** **EU (France)** — no **default** third-country transfer for hosting.

# GDPR — Article 32 measures (summary)

| Pillar | Implementation (high level) |
|--------|--------------------------------|
| **Confidentiality** | TLS 1.2/1.3 in transit; encryption at rest for snapshots/backups; Vault for secrets; tenant isolation |
| **Integrity** | Signed commits, checksums on backups, append-only style logging where applicable |
| **Availability** | Redundant Kubernetes design; OVH-managed control plane; **BCP/DR** documents in pack |
| **Resilience** | Tested restores (quarterly); documented RTO/RPO targets in PCA for the reference environment |
| **AI-specific** | Local inference stack — **no routine export of prompts to a third-party AI vendor** in the standard build |

# ISO/IEC 27001:2022 — four Annex A themes

| Theme | OVHcloud | Datategy |
|-------|----------|----------|
| **A.5 Organisational** | Public IS policy, compliance catalogue, contracts | PAS, governance, incidents, legal & DP annexes |
| **A.6 People** | DC physical security staff | HR onboarding/offboarding, training programme (pack) |
| **A.7 Physical** | **Full physical stack** at OVHcloud sites | N/A (Datategy does not host customer data on premises) |
| **A.8 Technological** | Hypervisor / network / managed K8s control plane | Mesh, identity, crypto, logging, backups, **local AI services**, secure SDLC |

*The Word note breaks this down to control level.*

# Security operations you can audit

- **Access:** Keycloak RBAC, strong password policy, MFA for admins, optional SSO to your IdP
- **Network:** Istio ingress, internal mTLS patterns, egress restrictions via Kubernetes **NetworkPolicy**
- **Secrets:** centralised in **Vault** with audit trail
- **Vulnerability management:** continuous scanning in CI; monthly patch cadence; CIS-style container checks
- **Logging & monitoring:** cluster and application logs, health checks, alerting
- **Incidents:** documented path in PAS; breach notification chain **Datategy → you → regulator** as required by law

# Business continuity & disaster recovery

- **PCA (BCP):** documented continuity approach — **reference RTO/RPO** in the published PCA (e.g. **6 h / 12 h** for the described test environment — production targets agreed per contract)
- **PRS (DR):** backup of persistent volumes, recovery playbook orientation
- **Backups:** encrypted snapshots with defined retention (hot / weekly / monthly) per PAS
- **Tests:** restore exercises on a defined cadence (documented in PAS/PCA family)

# Reversibility & exit

- **Data return:** open formats — DB dumps, object exports, models, scripts — over agreed secure channel (e.g. SFTP/FTPS)
- **Deletion:** secure wipe after contractual retention window; destruction evidence where applicable
- **Infrastructure:** Cinder volumes follow OVHcloud lifecycle and secure disposal practices

# Deliverable pack — `ANDRITZ-pack/`

| Folder | Contents |
|--------|----------|
| **`00_synthese/`** | **`fiche-hosting-ovh-andritz.docx`** — full structured note (ISO 27001:2022 + GDPR + architecture + AI) |
| **`01_datategy/`** | PAS, PCA, DR, privacy, DPA, SLA/support, training — **PDF** |
| **`02_ovhcloud/`** | **16 PDFs** — archived **public** OVHcloud compliance & legal pages |

**Plus:** `README.md` at pack root — navigation aid for reviewers.

# Why this supports a SaaS security review

- **Single narrative:** one Word note ties **architecture**, **shared responsibility**, **OVHcloud public assurance**, and **Datategy policies** to **ISO 27001:2022 Annex A**.
- **Evidence-first:** the pack is **self-contained** for a **first-pass** review without hunting URLs during the meeting.
- **AI clarity:** explicit **on-cluster** LLM/embedding design — addresses the **#1 enterprise question** on GenAI today.
- **Procurement-friendly:** maps cleanly to **security questionnaire** sections (hosting, subprocessors, crypto, logging, DR, DPAs).

# Recommended next steps

1. Circulate **`ANDRITZ-pack/`** (or at minimum **`00_synthese/fiche-hosting-ovh-andritz.docx`**) ahead of legal/security deep dive.
2. Align on **tenant DNS**, **IdP federation**, and **production RTO/RPO** targets in the order form / DPA schedules.
3. Schedule a **technical session** (optional): cluster hardening review, log retention, and backup restore drill witness.

# Thank you — contacts

- **Security:** security@datategy.net  
- **Data Protection:** dpo@datategy.net  
- **Support (operational):** support@papai.ai  

**Deck source:** `docs/compliance-2/fiche-hosting-ovh-andritz/ANDRITZ-hosting-compliance-deck.md`
