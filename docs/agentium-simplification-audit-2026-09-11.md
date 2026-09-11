# Agentium simplification audit and priority plan

Date: 2026-09-11

## Product decision

Agentium should ship as one dependable product with two depths, not as a catalog of partially connected modules.

- **Use Agentium** is the default. A person connects a model, optionally adds knowledge, asks a question, receives a grounded answer, and can recover from failure.
- **Build and operate** is progressive disclosure for technical users. They can turn the same working behavior into a System, inspect Runs, and manage runtime configuration.
- Commercial concepts that are not backed by a working loop are removed from the product UI. This includes marketplace framing, unit pricing, certification claims, and billing language.
- Stub, unbound, catalog-only, preview-only, and legacy surfaces do not appear in normal navigation. A developer diagnostics page may expose them explicitly.

The main success metric is activation: a new user gets one successful, sourced answer in under five minutes.

## Audit snapshot

### What is solid

- The repository has a real Angular application, FastAPI API, workspace scoping, model routing, streaming chat, knowledge ingestion, Runs, and runtime health contracts.
- The backend now classifies model failures with safe stable codes and exposes active model readiness.
- The UI has shared cockpit tokens, English and French dictionaries, navigation guardrails, workspace reset protection, and focused unit-test infrastructure.
- The mental model already states the right principle: business users start at Layer 0 and technical detail is progressively disclosed.

### What currently prevents a jump-in-and-use product

1. **The first screen is the wrong screen.** The root route redirects to Hypervisor even for a new personal workspace. This exposes strategic concepts before the user has completed one useful action.
2. **The visible product is wider than the working product.** The app registers a large set of top-level areas and 24 feature route modules. Several are specialized, legacy, flag-dependent, catalog-only, or configuration-heavy.
3. **Provider setup is disconnected from the first question.** A missing or unreachable model previously surfaced as `LLM generation error: All connection attempts failed` inside the answer. The user had no clear recovery action.
4. **Simple chat was not simple.** Quick Ask exposed reasoning templates, retrieval modes, runtime details, voice, traces, correction tools, evaluation scores, and operational diagnostics.
5. **Commercial promises exceed implementation truth.** Capability and Skill surfaces show unit price, ROI, SLA, and certification concepts. The product documentation states that billing and the certification pipeline do not exist.
6. **Non-working inventory is still discoverable.** The Apps page says `Catalog only · no runtime wiring yet`. Skills and builder flows may show stub or unbound entries and only warn that a Run may fail.
7. **Too many overlapping entry points exist.** Chat, Work, Apps, Systems, Capabilities, Orchestration, Tasks, Presets, Resources, Models, and Connectors each compete to explain how a user should begin.
8. **The repository carries historical product layers.** The root README still presents OmniRAG and legacy settings remain routable. This makes setup, contribution, and product ownership harder to understand.

## Target usage storyline

### Non-technical user

1. Sign in.
2. See one setup check: **Connect a model** if none is ready.
3. Land in **Ask**, with one composer and optional **Add files**.
4. Ask a question.
5. Receive a streamed answer with sources.
6. If the model fails, see a safe error card with **Try again** or **Model settings**. Any partial answer remains separate.
7. Continue the conversation or open the source. Nothing else is required.

### Technical user

1. Complete the same successful Ask flow.
2. Choose **Turn this into a System** from the working conversation or knowledge context.
3. Configure only required inputs. Advanced retrieval, model, policy, and flow controls stay collapsed until requested.
4. Test the System with a visible readiness checklist.
5. Publish only when every required runtime is bound and the test passes.
6. Operate through Runs and failures. Strategic steering appears only when real Outcome data exists.

### Administrator

1. Configure workspace identity and one model provider.
2. Validate credentials and selected model immediately.
3. Add users and knowledge sources.
4. See runtime health and failures in one diagnostics area.
5. Never manage fake pricing, marketplace, or certification data.

## What to keep, simplify, hide, and remove

| Area | Decision | Reason |
| --- | --- | --- |
| Quick Ask | Keep and make default | Fastest proof that Agentium works |
| Model provider setup | Keep, consolidate, and validate inline | Required dependency of every LLM workflow |
| Files and Knowledge | Keep, with one Add knowledge path | Core grounding value |
| Sources and conversation history | Keep | Trust and continuity |
| Systems | Keep for technical users | Core reusable execution object |
| Runs | Keep for technical users | Real execution evidence and recovery |
| Work experiences | Keep only deployed, working experiences | Useful business entry points when backed by a System |
| Hypervisor and Steering | Hide until measured Outcome data exists | Empty or configured-only strategic views undermine trust |
| Capabilities | Simplify to reusable business templates | Remove price, SLA, marketplace, and unsupported certification framing |
| Skills | Move under Build or Diagnostics | Technical inventory is not a primary product destination |
| Orchestration canvas | Advanced-only | Do not force DAG concepts on first-time users |
| Apps catalog | Remove from normal navigation | It explicitly has no runtime wiring |
| Connectors catalog | Show only configured and working connectors | Catalog breadth is not user value |
| Presets and legacy Settings | Merge into one Settings area | One place for model, workspace, language, and advanced defaults |
| Demo-specific cockpits | Keep behind explicit demo/workspace profiles | They should not define the generic product |
| Unit pricing and billing language | Remove | No billing subsystem exists |
| Skill certification tiers | Remove from product UI | No certification pipeline exists |
| Stub and unbound entries | Hide from normal users and block publication | A warning is not a working runtime |

## Priority plan

### P0: noticeable functional changes first

#### P0.1 Make Ask the default home

Change the root and new personal-workspace destination from Hypervisor to the simple Ask surface. Existing operator workspaces may keep a configured home.

Acceptance:

- A new user sees a composer or a single model-setup action after sign-in.
- No System, Capability, Run, Skill, Policy, or ROI vocabulary appears before the first successful answer.
- Returning users resume the last conversation or see an empty composer.

#### P0.2 Finish the model setup and recovery loop

Status: backend readiness and safe failure classification are implemented; Quick Ask readiness and structured recovery UI are implemented in this audit branch.

Next:

- Add a first-run model setup screen that validates credentials and model availability before saving.
- Return to the original question automatically after successful setup.
- Add a compact runtime diagnostics detail for technical users without exposing it in the answer.

Acceptance:

- Stopped Ollama, invalid credentials, missing model, rate limit, and timeout each produce the correct safe state and recovery action.
- No stack trace, URL, credential, raw exception, or `All connection attempts failed` text reaches the conversation.
- The user's question and partial answer survive recovery.

#### P0.3 Reduce primary navigation to four destinations

Recommended default navigation:

- **Ask**
- **Knowledge**
- **Build**
- **Runs**

Put workspace and model configuration under **Settings**. Put governance and deep runtime status under an admin-only **Diagnostics** entry. Hide Hypervisor and Steering until the workspace has measured Outcome data.

Acceptance:

- A normal member sees at most four primary destinations.
- A technical role can reach every retained advanced surface within two actions.
- Removed destinations still resolve through existing deep links during one compatibility release.

#### P0.4 Remove unsupported commercial UI

Remove from normal product surfaces:

- Capability and Skill unit price columns and cards.
- Pricing-based ROI calculations that depend on manually seeded price fields.
- Marketplace wording and search keywords.
- Skill certification badges, filters, and claims.
- Billing, subscription, upgrade-plan, or purchase language unrelated to a real business workflow.

Do not remove real business prices inside Client360 or procurement workflows. Those are domain data, not Agentium commercial packaging.

Backend fields may remain read-only for one migration window if existing data depends on them, but the API must mark them deprecated and new writes must stop.

Acceptance:

- Global search for product-package pricing and certification terms returns only migration code and historical documentation.
- Capability and Skill creation contains no price or certification input.
- No screen implies that Agentium can invoice, sell marketplace items, or certify a Skill.

#### P0.5 Fail closed on non-working features

- Do not list Apps that are catalog-only.
- Do not allow a System to publish or run with required stub, unbound, or catalog-only Skills.
- Do not show a connector as available until its credential check and one read operation pass.
- Replace placeholder buttons with disabled states that explain the missing prerequisite, or remove them.

Acceptance:

- Every visible primary action has an automated success-path test.
- Runtime readiness is authoritative. Catalog presence never equals availability.
- A release cannot be published with unresolved required dependencies.

#### P0.6 Prove one golden path in a clean workspace

Create one deterministic end-to-end test and demo seed:

`sign in → connect model → add one document → ask one question → open one source → retry one forced failure`

Acceptance:

- The flow passes from an empty database on the supported local Docker profile.
- The same flow passes in English and French.
- The test records time to first answer and fails above the agreed budget.

### P1: simplify structure after the first-use loop works

#### P1.1 Merge overlapping model and settings surfaces

Create one Model settings route for provider credentials, active model, health, and test action. Redirect Models, Resources provider facet, Presets model defaults, and legacy Settings model configuration to it.

#### P1.2 Turn Knowledge into one progressive flow

One entry supports upload, processing status, failure recovery, collection assignment, and Ask. Advanced chunking, embeddings, metadata, and retrieval tuning stay behind **Advanced**.

#### P1.3 Simplify Build around a working template

Start from objective, knowledge, and output. Derive a default System and Flow. Reveal Skills and policy only when the user chooses Advanced. Block publication on readiness rather than showing warnings.

#### P1.4 Consolidate Work, Tasks, and deployed Apps

Keep **Work** as the launcher for deployed business experiences. Remove the separate Apps catalog from user navigation. Tasks belong inside the experience or Run that owns them unless there is a proven cross-experience inbox.

#### P1.5 Retire legacy routes and vocabulary

Redirect then remove legacy Settings, old agent/trace/playground aliases, and stale OmniRAG entry documentation. Update the root README to describe Agentium, its supported start command, and the golden path.

### P2: harden and polish

#### P2.1 Accessibility and responsive pass

- Validate keyboard order, visible focus, live-region behavior, 200 percent zoom, narrow layouts, touch targets, reduced motion, and contrast.
- Add automated axe coverage for Ask, setup, Knowledge, Build, and Runs.

#### P2.2 Performance and perceived speed

- Measure sign-in to usable composer, route bundle sizes, readiness latency, first token, and source rendering.
- Lazy-load advanced controls and diagnostics.
- Keep every local state response under 300 ms perceived time.

#### P2.3 Observability for the product team

Track only the funnel needed to improve activation:

- Signed in.
- Model ready.
- Knowledge added.
- First question sent.
- First answer completed.
- Source opened.
- Failure recovered.
- System published.

#### P2.4 Visual system cleanup

Apply the Cockpit Workbench token system consistently. Remove remaining legacy violet gradients, decorative glow, glass styling, side-stripe callouts, oversized icon tiles, and repeated nested cards from generic product surfaces.

### P3: reintroduce advanced strategy only after evidence exists

Hypervisor, Steering, Outcome economics, marketplace concepts, certification, and broad connector catalogs should return only when each has:

1. A real backend contract.
2. Real persisted data.
3. A complete user action loop.
4. Automated success and failure tests.
5. Evidence that target users need it.

Until then, keep the code behind explicit experimental flags or remove it.

## Delivery sequence

| Order | Delivery | User-visible outcome |
| --- | --- | --- |
| 1 | Quick Ask readiness and recovery | The current connection error becomes understandable and recoverable |
| 2 | Ask as default home | New users immediately know what to do |
| 3 | Four-item navigation | The product feels smaller and learnable |
| 4 | Remove unsupported commercial UI | The interface stops promising billing, marketplace, and certification |
| 5 | Hide or block non-working runtimes | Visible features become trustworthy |
| 6 | Golden-path setup and E2E | A clean install proves the product works |
| 7 | Merge Settings and Knowledge flows | Setup and grounding become easy |
| 8 | Simplify Build | Technical users can graduate from Ask to a System |
| 9 | Accessibility, speed, telemetry | The core becomes release-grade |
| 10 | Evaluate advanced surfaces | Features return only with evidence and working loops |

## Lessons borrowed from Dify, without copying Dify

Dify's current official workflow documentation consistently stages work as create, configure, test, then publish. Its model-provider contract validates credentials and distinguishes provider-level setup from model-level configuration. Those are useful interaction lessons for Agentium.

Agentium should borrow:

- One obvious creation or use entry.
- Strong defaults with optional advanced configuration.
- Credential validation at setup time.
- Test before publish.
- Logs and technical detail after a failure, not before the first action.

Agentium should not copy:

- A workflow canvas as the default mental model.
- A broad plugin marketplace before runtime quality is proven.
- Separate app types that fragment the simple user story.

Sources:

- [Dify 30-Minute Quick Start](https://docs.dify.ai/en/guides/application-orchestrate/creating-an-application)
- [Dify model provider configuration and credential validation](https://docs.dify.ai/en/develop-plugin/dev-guides-and-walkthroughs/creating-new-model-provider)

## Release gates

No simplification phase is complete until:

- Focused unit and integration tests pass.
- The clean-workspace golden path passes.
- English and French keys remain equivalent.
- Navigation uses canonical links and retains workspace scope.
- No raw provider exception is rendered.
- No user-owned unrelated working-tree change is included.
- Product documentation describes only verified behavior.
