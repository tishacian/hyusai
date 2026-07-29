# Agentium Showcase — Onboarding & Hands-On Guide

**For PIH evaluation participants · July 2026 · Confidential**

Welcome to your Agentium workspace. This note tells you how to get in, what you
will find once your access is active, and where the topics you care most about
live in the platform: Flow Builder, Systems, replay, skills, observability,
orchestration/automation (RPA) and data-source connectivity (SAP, Databricks,
UiPath). A dedicated guided hands-on session with our team will follow — see
section 5.

---

## 1 · Before you start — a note on releases

Agentium is a **live platform, in production at client sites** (Renault Group,
Andritz, Société du Grand Paris, Mobilize Financial Services, among others).
The Showcase workspace you are accessing runs on our SaaS environment, which
follows a **continuous-improvement release cycle**: we are currently rolling
out a new version, so some screens may be refined between your sessions. Two
things will not change under you:

- **The mental model** (below) — objects, their relationships and the
  governance chain are stable.
- **Your data and flows** in the Showcase workspace persist across releases.

If a button has moved, the concept is still there — and telling us what you
expected to find is exactly the feedback we want.

## 2 · Getting in

1. You will receive a **personal invitation email** (sender: Agentium /
   Datategy). Follow the link to set your password — the login page is the
   branded Agentium portal.
2. After login, make sure the workspace selector (top bar) shows
   **Showcase** — that is your shared evaluation environment.
3. Everything in Showcase runs on **synthetic or anonymised data**. Feel free
   to click, edit, run and break things: nothing touches any production system.

## 3 · The mental model — five objects, one chain

Everything in Agentium hangs off one canonical chain:

> **System → Flow → Run → Evaluation → Decision → Ledger**

| Object | What it is | Where you see it |
|---|---|---|
| **System** | A governed business capability (e.g. "Contract Risk", "Hydro Plant Insights"). Owns its flows, runs, metrics and evidence. | Portfolio / System 360 |
| **Flow** | The executable definition — a visual DAG of **typed skills** assembled in the Flow Builder. | Flow Builder |
| **Skill** | A typed, reusable unit of work (query SAP, call an LLM, dispatch an RPA job…). Skills are what connectors contribute to the catalog. | Node palette / skills catalog |
| **Run** | One execution of a flow: stateful, resumable, fully traced (every step, tool call and cost), and **replayable**. | Runs / Run detail |
| **Decision / Gate** | A human-in-the-loop checkpoint inside a run — with expiry rules, so a run never waits forever. | Run detail / inbox |

**System 360** shows each System through four perspectives — **Build**
(flows & skills), **Operate** (runs & incidents), **Steer** (cost, value, ROI —
the Hypervisor), **Govern** (decisions, audit evidence). Same object, four
lenses; whatever evolves in the UI, this is the map.

## 4 · What you will find once your access is active

The Showcase workspace comes pre-populated, so there is something meaningful
behind every door from the first login:

- **A portfolio of showcase Systems** — the Hypervisor home lists governed
  business capabilities, each carrying its own flows, runs, cost/value metrics
  and audit evidence; explore any of them through the four System 360
  perspectives (Build / Operate / Steer / Govern).
- **Ready-made flows in the Flow Builder** — demo flows, including an
  **SAP hydro insights** flow wired to a seeded HANA dataset, open as visual
  DAGs of typed skills. Node parameters (SQL statements, analysis questions)
  are inspectable and editable in place.
- **Run history with full traces** — past executions with step-by-step traces
  (inputs, outputs, timing, cost per step), plus **Rerun** to replay any DAG
  and compare executions side by side.
- **A skills & connectors catalog** — typed skills contributed by connectors,
  e.g. `sap_hana_query_v1` (SAP HANA Cloud) and `rpa_dispatch_v1` (RPA
  Bridge), alongside the **Models & Providers** portal with wired LLM
  providers and per-workspace routing.
- **Orchestration primitives** — trigger nodes (schedules, signed webhooks,
  file-arrival events), human decision gates with expiry rules, and a run
  inbox for long-lived processes. The RPA Bridge dispatches jobs through a
  generic REST contract (a mock orchestrator answers in the Showcase).

Feel free to browse and run what is there. For the structured hands-on part —
building and modifying flows yourselves, replay scenarios, connector
configuration — we will schedule a **dedicated guided session** with our team
(section 5): it is the fastest way to get real value from the platform.

## 5 · Guided hands-on session — the next step

Rather than leaving you alone with a set of exercises, we propose a **live
guided hands-on session (60–90 min)** with our team, scheduled at your
convenience shortly after your access is confirmed. Agenda, driven by your
priorities:

- Build and edit a flow end-to-end in the **Flow Builder**, and execute it live.
- **Replay** a run and walk its full trace — inputs, outputs, timing, cost per step.
- Configure a **connector** (SAP HANA Cloud) and see its skills land in the catalog.
- **Orchestration & RPA** — triggers, decision gates, and job dispatch through
  the RPA Bridge.
- Open Q&A on architecture, governance and your evaluation criteria.

Your Datategy contact (see invitation email) will propose slots. In the
meantime, individual exploration of the Showcase is welcome — nothing you do
there can break anything.

## 6 · Your focus areas — where each one lives

| Your topic | Where to look | Today's status in Showcase |
|---|---|---|
| Flow Builder | Build perspective → Flow Builder | Live — editable Node Inspector, Execute, run results in place |
| System / System 360 | Portfolio → any System | Live — four perspectives (Build/Operate/Steer/Govern) |
| Replay | Run detail → Rerun | Live — DAG-level replay; certified replay with evidence file is the R&D axis presented in the deck |
| Skills | Node palette / catalog | Live — typed skills, connector-contributed |
| Observability | Operate + Steer (Hypervisor) | Live — traces, cost per step, portfolio cost/value/ROI |
| Orchestration | Triggers, gates, run inbox, memory | Live — schedules, webhooks, durable gates with expiry |
| Automation (RPA / UiPath) | RPA Bridge + `rpa_dispatch_v1` | Live via generic REST bridge (mock orchestrator in Showcase); the same contract maps 1:1 to UiPath Orchestrator — dedicated UiPath profiles mobilise with 60 days' notice, per our RFI response |
| SAP connectivity | Connectors → SAP HANA Cloud | Live — encrypted config, test/query, demo dataset seeded |
| Databricks connectivity | Connectors rail | Same connector pattern (SQL endpoint); walkthrough on request — our agents consume governed data products through Unity Catalog, as described in our RFI response |

## 7 · Ground rules & support

- **Data**: synthetic/anonymised only. Please do not upload PIH production data
  to the Showcase tenant.
- **Licence**: time-boxed evaluation access; no commercial commitment implied.
- **Audit**: every action in the workspace is ledgered — you are welcome to
  inspect your own trail; that is the governance working.
- **Support**: one named Datategy contact (see invitation email) · guided
  session on request · feedback goes straight into the pilot design.

*The same platform you are touching deploys unchanged to an Azure Qatar
tenancy, on-premise or air-gapped — what you evaluate is what you get.*

— Datategy · AI & Data Center of Excellence
