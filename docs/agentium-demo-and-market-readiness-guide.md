# Agentium demo and market-readiness guide

Date: 2026-09-14

This guide has three purposes:

1. State honestly how much of the simplification plan is complete.
2. Provide a repeatable, step-by-step Agentium demonstration.
3. Explain where Agentium fits relative to Dify and what can be delivered today.

The source plan is `docs/agentium-simplification-audit-2026-09-11.md`. The
implementation evidence is tracked in
`docs/agentium-simplification-implementation-progress.md`.

## 1. Is the entire simplification plan finished?

**Yes for the planned P0–P2 simplification scope.** The implementation and the
original release rules now pass on the supported isolated local profile. P3 is
not unfinished work: it deliberately keeps advanced strategy and unsupported
commercial/catalog concepts out of the normal product until real demand and a
complete working loop justify them.

The accurate status is:

- **15 of 15 P0–P2 work items meet their stated completion criteria.**
- **P2.1 is live-certified** across the full core browser matrix.
- **P0.6 passes** in English and French, including repeated runs on a populated
  workspace and a forced connection failure followed by a cited retry.
- **P3 is intentionally deferred**, not missing implementation. The plan says
  advanced strategy and marketplace features must remain hidden until evidence
  proves they are needed and fully functional.

### Plan-by-plan audit

| Plan item | Status | Evidence or remaining gap |
| --- | --- | --- |
| P0.1 Ask as default home | Done | The authenticated root resolves to `/chat?mode=quick`. |
| P0.2 Model setup and recovery | Done | Settings validates a provider/model before saving; failed questions can be retried after setup; safe errors replace raw connection exceptions. |
| P0.3 Four primary destinations | Done | Standard navigation is Ask, Knowledge, Build, and Runs. |
| P0.4 Remove unsupported commercial UI | Done | Product pricing, marketplace, certification, billing, and purchase claims were removed from normal product surfaces. |
| P0.5 Fail closed on non-working features | Done | Catalog-only Apps are not exposed as runnable; required unbound or stub Skills block publish/run. |
| P0.6 Clean-workspace golden path | Done | The authenticated EN/FR Playwright flow passes setup, upload, cited answer, rendered source, forced failure, and cited recovery. Unique evidence references keep repeated runs deterministic on a populated store. |
| P1.1 One model/settings surface | Done | `/settings` is the focused model setup route; old model settings routes redirect to it. |
| P1.2 Progressive Knowledge flow | Done | Upload, processing, recovery, collections, Ask, and Advanced disclosure are implemented. |
| P1.3 Simplified Build flow | Done | The default builder begins with objective and knowledge; advanced controls are disclosed on demand; readiness blocks unsafe publication. |
| P1.4 Consolidate Work, Tasks, Apps | Done in product navigation | Work launches deployed experiences, Tasks resolves into Runs, and the separate Apps catalog is absent from primary navigation. |
| P1.5 Retire legacy routes/vocabulary | Done | Legacy settings, agents, traces, and playground routes redirect; the root README describes Agentium rather than the retired OmniRAG UI. |
| P2.1 Accessibility/responsive pass | Done | The authenticated real-browser matrix passes Ask, Settings, Knowledge, Build, and Runs across EN/FR, light/dark, reduced motion, desktop, 456 px, and 320 px. |
| P2.2 Performance | Done | The current production build passes at 854,312 initial bytes, below the unchanged 1 MB budget; core routes and heavy libraries remain lazy. |
| P2.3 Activation telemetry | Done | Eight privacy-safe funnel milestones are emitted through the workspace audit mechanism. |
| P2.4 Visual cleanup | Done | The five core surfaces use flatter Cockpit tokens, less decorative styling, and explicit narrow-screen behavior. |
| P3 Advanced strategy | Intentionally out of scope | Hypervisor, Steering, outcome economics, marketplace, certification, and broad connector catalogs should return only with real data, complete loops, tests, and user evidence. |

### Release-gate verdict

| Original release gate | Result |
| --- | --- |
| Focused unit and integration tests pass | Pass; the complete frontend suite passed 1,545/1,545. |
| Clean-workspace golden path passes | Pass; it also passes repeatedly on the intentionally reused isolated workspace. |
| English and French keys remain equivalent | Pass statically and in the behavioral golden journey. |
| Canonical navigation retains workspace scope | Pass. |
| No raw provider exception is rendered | Pass through source and unit contracts. |
| No unrelated user change is included | Pass. The existing `frontend-ng/proxy.conf.json` edit remains outside Agentium commits. |
| Documentation describes verified behavior only | Pass, provided Agentium is presented with the scope boundaries in this guide. |

## 2. What Agentium is now

Agentium is a governed workspace for turning trusted knowledge into answers,
reusable AI Systems, and inspectable Runs.

The simple user story is:

> Connect one model → add trusted knowledge → ask a sourced question → turn a
> working behavior into a System → inspect its Runs.

It has two depths:

- **Use Agentium:** Ask, add files, read cited answers, and recover from model
  failures without learning orchestration terminology.
- **Build and operate:** Create a reusable System, disclose advanced controls
  only when needed, publish only when its runtime is ready, and inspect Runs
  and Skill invocations.

## 3. Demo prerequisites

Prepare these before presenting:

- A running Agentium backend and Angular frontend.
- A test user that belongs to a dedicated demo workspace.
- One working LLM provider. Ollama is convenient for a private local demo; a
  cloud provider needs a demo-only API key.
- One small, non-confidential PDF, DOCX, TXT, or Markdown document.
- An empty or disposable workspace so the setup and recovery story is visible.

Do not use production credentials or a customer workspace in a public demo.

### Start Agentium locally

From the repository root, start the backend in one terminal:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements/celery.txt -r requirements/cpu.txt -r requirements/test.txt
cd backend
uvicorn app.main:app --reload
```

Start the frontend in a second terminal:

```bash
cd frontend-ng
npm ci
npm run start
```

Open `http://localhost:4200`. For the verified isolated release profile used on
2026-09-14, the preview was served at `http://127.0.0.1:4210` with the API at
`http://127.0.0.1:8010`; these alternate ports avoid disturbing a developer's
normal `4200`/`8000` processes.

### Five-minute preflight

Before the audience joins:

1. Confirm `http://localhost:4200` loads.
2. Confirm the backend health endpoint answers successfully.
3. Sign in with the demo identity.
4. Open `/settings` and confirm the chosen model says it is ready.
5. Upload the demonstration document once in a disposable rehearsal workspace.
6. Ask the main question and confirm the answer has at least one source.
7. Open the source preview.
8. Confirm `/runs` contains the expected completed Run.
9. Reset or switch to the clean presentation workspace.

If any check fails, do not improvise claims. Show the recovery state or switch
to a previously validated workspace.

## 4. Recommended 15-minute product demo

### Act 1 — Start with a useful action (1 minute)

1. Sign in.
2. Show that Agentium lands directly in **Ask**.
3. Point to the four primary destinations: **Ask**, **Knowledge**, **Build**,
   and **Runs**.

Say:

> Agentium begins with the job the user wants to do. Architecture, Skills,
> routing, and traces are available later, but they are not prerequisites for
> asking a useful question.

Success evidence: the composer is usable, or there is one explicit
**Connect a model** action.

### Act 2 — Connect and verify one model (2 minutes)

1. Open **Settings** or follow **Connect a model** from Ask.
2. Select the provider.
3. Enter the provider endpoint or demo key, if required.
4. Select the actual installed/available model.
5. Save.
6. Wait for the readiness result before leaving the page.

Show both truths if useful:

- A valid provider becomes ready only after live validation.
- An invalid key, stopped local provider, missing model, rate limit, or timeout
  produces a safe recovery state rather than a raw exception.

Do not reveal the API key, internal URL, stack trace, or provider exception on
the presentation screen.

### Act 3 — Add trusted knowledge (3 minutes)

1. Open **Knowledge**.
2. Drop the prepared document into the upload area.
3. Show its processing state.
4. Wait until the document is ready.
5. If useful, assign or open its collection.
6. Keep **Advanced** closed for a business audience.

Say:

> Agentium does not ask the model to guess from public training data. It first
> retrieves relevant workspace evidence, then uses that evidence to answer.

For a technical audience, open **Advanced** after the simple flow works and
show that capture, metadata, retrieval, or collection controls are secondary
options rather than initial obstacles.

### Act 4 — Ask, verify, and recover (4 minutes)

1. Return to **Ask**.
2. Select the relevant knowledge context if it is not already active.
3. Ask one precise question whose answer is present in the uploaded document.
4. Let the answer stream to completion.
5. Point out the source citation.
6. Open the source preview and connect the answer to the exact evidence.
7. Ask one follow-up question to demonstrate conversation continuity.

Recommended questions when this guide itself is the uploaded document:

- `What is Agentium's recommended market position, and what should it not claim to be?`
- `Which release gates are still incomplete?`
- `Give me the five steps in the Agentium product story and cite the source.`

To demonstrate recovery safely, stop the disposable local provider or use the
test’s forced transport failure. Show that:

- the original question remains visible;
- partial output is not presented as a complete answer;
- the error explains the next action;
- **Try again** or **Model settings** recovers the same task.

Do not deliberately break a shared cloud account during a customer demo.

### Act 5 — Turn working behavior into a System (3 minutes)

1. Open **Build**.
2. Create a new System.
3. Describe the desired result in plain language.
4. Select the trusted knowledge source.
5. Use the recommended runnable capability.
6. Keep model, retrieval, Skill, policy, and Flow controls collapsed initially.
7. Open **Advanced** for the technical audience only.
8. Review readiness.
9. Publish only if every required runtime is bound and ready.

Say:

> A System is not a catalog card or a promise. It is a reusable behavior that
> can be published only when its dependencies can really execute.

If readiness blocks publication, treat that as a successful governance demo.
Do not bypass it.

### Act 6 — Inspect execution evidence (2 minutes)

1. Open **Runs**.
2. Filter by status or experience origin if needed.
3. Open the newest Run.
4. Show status, timing, inputs/outputs appropriate for the audience, and the
   execution path.
5. Open a Skill invocation when one exists.
6. Explain where a technical operator diagnoses a failed or slow step.

Say:

> The user sees a simple answer or business result. The operator can still
> inspect the Run and the runtime evidence behind it.

## 5. Extended capability tour

Use this section only after the core demonstration succeeds.

| Capability | What to show | Scope rule |
| --- | --- | --- |
| Grounded Ask | Streaming answers, history, context selection, files, citations, source preview, safe retry | Core product |
| Knowledge | Upload, processing/recovery, collections, document view, retrieval context | Core product |
| Knowledge capture | Workspace or System-scoped guided capture | Advanced; demonstrate only with the correct workspace flag/profile |
| Systems | Objective-first builder, knowledge binding, capability selection, readiness, publish | Core technical product |
| Flow builder/runner | System flow route and execution | Advanced; not the default mental model |
| Runs | Status filtering, Run detail, Skill invocation detail, failure inspection | Core technical product |
| Work | Launcher for already deployed business experiences | Show only a seeded, working experience |
| Provider administration | Validated provider/model setup, defaults, health, technical details | Admin/technical |
| Connectors | Configured connector health and verified read behavior | Never demonstrate catalog-only entries as available |
| Governance and account | Workspace access, identity, audit surfaces | Enterprise/administrator; verify the target deployment first |
| Data/ML, Client360, NAWA, Mission Room, voice, and specialized cockpits | Profile-specific business demonstrations | Separate products/demos; not part of the generic Agentium first-use promise |
| Hypervisor, Steering, outcome economics | Strategic views backed by measured outcome data | Deferred by P3 unless a deployment has real persisted data and tested actions |

## 6. What must not be claimed

Do not claim that Agentium currently provides:

- a public marketplace;
- Skill certification;
- metered billing, subscriptions, invoicing, or plan upgrades;
- hundreds of production-ready providers and plugins;
- every visible catalog connector as a working integration;
- one-click public web-app, embed, or MCP publishing;
- a turnkey hosted SaaS onboarding experience;
- broad production certification beyond the documented local release profile
  and the deployment-specific provider matrix.

Real prices inside a business workflow, such as procurement data, are valid
domain data. They are not Agentium product pricing.

## 7. Agentium compared with Dify

This comparison uses Dify’s official documentation and public repositories as
of 2026-09-14. It compares product scope, not code quality.

Dify describes itself as an open-source AI application platform combining
visual workflows, RAG, agents, model management, observability, APIs, cloud,
and self-hosting. Its current publishing options include generated web apps,
APIs, website embeds, and MCP servers. Dify also maintains a model/tool plugin
ecosystem and a marketplace.

| Dimension | Agentium today | Dify today | Practical verdict |
| --- | --- | --- | --- |
| First-use story | Ask-first: model → knowledge → sourced answer | Build-first application platform with guided first-app material | Agentium is simpler for an internal knowledge user; Dify is clearer for an app builder. |
| Grounded Q&A | Strong core: upload, retrieval, citations, source preview, retry | Broad RAG product with ready-made and custom knowledge pipelines | Agentium can compete on the focused internal Q&A journey, but not yet on source/pipeline breadth. |
| Model providers | Multiple provider implementations exist, but the supported, verified matrix is narrower and deployment-dependent | Provider plugins, workspace setup, custom models, multiple credentials, and load balancing | Dify is materially ahead in breadth and self-service administration. |
| Visual workflows | Advanced System Flow exists but is deliberately not the default | Visual Workflow/Chatflow canvas is a flagship capability | Do not sell Agentium as a general no-code workflow-builder replacement. |
| Agents and tools | Governed Systems, runnable Skills, fail-closed readiness | Broad Agent/tool/plugin ecosystem and marketplace | Agentium’s differentiation is runtime trust; Dify wins ecosystem breadth. |
| Knowledge testing | User flow proves answers through citations; advanced retrieval exists | Dedicated retrieval testing, records, settings experiments, metadata, and custom pipelines | Agentium needs a clearer productized retrieval evaluation experience to match Dify. |
| Publishing | Internal Systems, Runs, APIs, and deployed Work experiences | Automatic web app, API, embed, and MCP access points | This is Agentium’s largest go-to-market gap for horizontal platform competition. |
| Operations | Runs and Skill-invocation evidence; workspace audit and activation telemetry | App conversations/runs, token/latency data, node traces, feedback, annotations, integrations | Both have credible foundations; Agentium should demonstrate its evidence depth on one real deployment. |
| Enterprise governance | Workspace scoping, RBAC-oriented routes, Keycloak integration, audit/governance surfaces | Workspace roles, member operations, logs, Cloud and Enterprise offers | Agentium can differentiate in controlled private deployments, but must certify the complete deployment path. |
| Installation | Multi-service developer/enterprise stack | Documented Docker Compose quick start plus managed Cloud | Agentium is not yet as jump-in-and-use operationally. |
| Commercial product | No fake pricing or marketplace claims; bespoke/private delivery is possible | Free Sandbox, paid Cloud tiers, Enterprise, billing and quotas | Agentium should sell a scoped deployment/outcome, not a Dify-like self-service subscription today. |

### Dify sources

- [Dify official repository and feature overview](https://github.com/langgenius/dify)
- [Dify 30-Minute Quick Start](https://docs.dify.ai/en/guides/application-orchestrate/creating-an-application)
- [Dify model-provider and credential-validation contract](https://docs.dify.ai/en/develop-plugin/features-and-specs/plugin-types/model-schema)
- [Dify plugin types](https://docs.dify.ai/en/develop-plugin/getting-started/choose-plugin-type)
- [Dify plugin distribution and Marketplace](https://docs.dify.ai/en/develop-plugin/publishing/marketplace-listing/release-overview)
- [Dify official model/tool plugins](https://github.com/langgenius/dify-official-plugins)

## 8. Market-delivery recommendation

### Deliverable now: controlled pilot

Agentium can be delivered now as a **controlled private pilot** when the offer
is narrow and concrete:

> A governed enterprise knowledge-to-operation workspace that produces sourced
> answers, turns validated behavior into reusable Systems, and exposes auditable
> Runs.

A responsible pilot includes:

- one customer or internal workspace;
- one or two validated model providers;
- a bounded document set and use case;
- one System or deployed Work experience;
- named administrators and users;
- monitored Runs and a documented recovery process;
- explicit acceptance tests and support ownership.

Good first markets are document-heavy internal workflows where evidence and
deployment control matter more than a plugin marketplace: internal policy Q&A,
technical field knowledge, procurement document assistance, controlled research,
or regulated operations support.

### Not deliverable yet: horizontal Dify competitor

Agentium should not yet be sold as:

- a self-service SaaS for any user;
- a general-purpose no-code AI application builder;
- a drop-in Dify replacement;
- a broad integration marketplace;
- an automatically published public app platform.

Those claims would require provider/plugin breadth, a simpler install or hosted
onboarding path, public distribution channels, stronger productized evaluation,
and repeatable release certification.

### Required before a general release

Priority order:

1. **Make startup repeatable:** one supported Docker or installer path, health
   checks, seed/reset commands, backup/restore, and a ten-minute operator guide.
2. **Publish a supported provider matrix:** list exactly which chat, embedding,
   rerank, and tool-calling combinations are tested.
3. **Choose a distribution promise:** internal Work experience plus API may be
   sufficient for the enterprise position. Web app/embed/MCP publishing is
   required only if Agentium chooses to compete with Dify’s horizontal platform.
4. **Prove one production workload:** capture success rate, cited-answer quality,
   p95 latency, recovery rate, and operator effort for one bounded use case.
5. **Certify operations:** RBAC, audit, secret handling, upgrades, rollback,
   retention, backup, and incident ownership.

## 9. Demo scorecard

Use this after every rehearsal or customer session.

| Check | Target | Result |
| --- | --- | --- |
| Sign-in to usable Ask | Within the configured performance budget |  |
| Model validation | Clear ready or actionable failure state |  |
| Document ingestion | Reaches ready state without manual repair |  |
| First grounded answer | At least one correct citation; under 45 seconds in the release gate |  |
| Source preview | Opens the cited evidence |  |
| Forced recovery | Same question retries successfully |  |
| System readiness | Publish succeeds only with real dependencies |  |
| Run evidence | Latest execution is inspectable |  |
| Business clarity | Audience can repeat the five-step story |  |
| Scope honesty | No unsupported marketplace, billing, connector, or certification claim |  |

## 10. Closing script

> Agentium is not trying to be the widest AI catalog. Its value is a shorter,
> governed path from trusted knowledge to a working result: ask, verify the
> source, reuse the behavior as a System, and inspect every Run. Today that is
> suitable for a controlled enterprise pilot. General self-service platform
> claims remain out of scope until startup, the supported provider matrix, and
> the distribution story are productized.
