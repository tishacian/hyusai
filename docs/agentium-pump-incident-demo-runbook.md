# Agentium pump-incident demo runbook

Date: 2026-09-14

This is the **recommended concrete Agentium demonstration**. It is a complete,
hands-on kit: a realistic business scenario, the exact files to upload, the exact
words to type, the exact answer facts to expect, and a ROI model built on editable
assumptions.

You do not need to know this repository to run it. Everything you need is in this
document and in `demo-assets/pump-incident-demo/`.

- Demo kit and files: `demo-assets/pump-incident-demo/README.md`
- Expected facts and prompts, machine-readable: `demo-assets/pump-incident-demo/expected/expected-facts.json`
- ROI model: `demo-assets/pump-incident-demo/roi/roi-model.md`
- Wider product positioning and scope rules: [`docs/agentium-demo-and-market-readiness-guide.md`](agentium-demo-and-market-readiness-guide.md)

> **All demo data is synthetic.** Nordvane Fluid Systems SA, Helioforge Paper Mill,
> every person, site, identifier, price and date in this kit was invented for this
> demonstration. Nothing here is customer or confidential data, and no figure here
> is an Agentium price.

---

## 1. Audience and outcome

### Who this is for

| Audience | What they should take away |
| --- | --- |
| Business evaluator, non-technical | "My team could get a defensible answer in seconds instead of digging through four documents, and I can see where the answer came from." |
| Operations or service manager | "The system refuses to guess, it shows its evidence, and it recovers when something breaks." |
| Technical evaluator or architect | "Retrieval is real, citations resolve to the actual file, readiness fails closed, and every execution leaves inspectable evidence." |

### The business scenario

A field-service team at **Nordvane Fluid Systems SA** must resolve high-priority
incident **NVX-INC-4821**: boiler feed-water pump **NVX-PUMP-7742** at
**Helioforge Paper Mill** is leaking and vibrating, the plant is running at reduced
production, and a **SLA-PLATINUM-04** restoration deadline is ticking.

### Why it proves something

The answer is not in any one document:

| The question the team must answer | Where the fact lives |
| --- | --- |
| Can the pump be restarted? | Measurement in the **incident brief**, threshold in the **procedure PDF** |
| What part is needed, and who has it? | Requirement in the **procedure PDF**, stock in the **inventory CSV** |
| By when must it be fixed, and what does late cost? | **Service-level policy** plus the incident open time |
| What is allowed while the part is in transit? | **Procedure PDF**, plus the French **service note** for the approver |

A single-document lookup cannot produce this answer. Synthesis across four
sources can, and every claim is citable.

### The outcome you are demonstrating

> Connect one model → add trusted knowledge → ask a sourced question → turn a
> working behaviour into a System → inspect its Runs.

---

## 2. Five-minute preflight

Do this **before** the audience joins. If a check fails, fix it or fall back to a
rehearsed workspace. Never improvise a claim on stage.

| # | Check | How | Pass looks like |
| --- | --- | --- | --- |
| 1 | The app loads | Open `http://127.0.0.1:4210` | The sign-in page or the workspace renders |
| 2 | You are signed in with the demo identity | Sign in | The shell appears and lands on **Ask** |
| 3 | Ask is the landing surface | Look at the address bar | It resolves to `/chat?mode=quick` |
| 4 | The four destinations are present | Look at the left rail | **Ask**, **Knowledge**, **Build**, **Runs** |
| 5 | A model is ready | Open **Settings** (`/settings`) | The **Set up the model** card shows your provider and model |
| 6 | Ask reports readiness | Return to **Ask** | The readiness strip says **Assistant ready** |
| 7 | The demo files are on the presenting machine | Open `demo-assets/pump-incident-demo/upload/` | Six files, listed in section 4 |
| 8 | The kit is self-consistent | From `demo-assets/pump-incident-demo/`, run `python3 tools/validate_demo_kit.py` | `OK: the demo kit is internally consistent.` |
| 9 | The workspace is clean or rehearsed | Open **Knowledge** | Either empty, or holding only this kit's documents |

Ports: `http://127.0.0.1:4210` with the API at `http://127.0.0.1:8010` is the
isolated release profile. A plain developer machine serves the same app at
`http://localhost:4200` with the API at `127.0.0.1:8000`. Use whichever your
environment actually runs; every navigation path below is relative to it.

**Do not show on screen:** API keys, internal URLs, stack traces, other customers'
workspaces.

---

## 3. Timing plan

| Act | Minutes | What happens |
| --- | --- | --- |
| 1 | 1 | Land in Ask, name the four destinations |
| 2 | 2 | Connect and verify one model |
| 3 | 3 | Upload the trusted knowledge |
| 4 | 5 | The grounded decision, its citations, and the source preview |
| 5 | 2 | Follow-up, exact-reference retrieval, and safe abstention |
| 6 | 2 | French |
| 7 | 2 | Forced failure and recovery |
| 8 | 3 | Build a reusable System, respecting readiness |
| 9 | 2 | Inspect Run and Skill evidence |
| **Total** | **20** | Drop acts 8 and 9 for a 15-minute business-only version |

---

## 4. The files, and the order to upload them

All paths are inside `demo-assets/pump-incident-demo/upload/`.

| # | File | Format | What it contributes |
| --- | --- | --- | --- |
| 1 | `demo-assets/pump-incident-demo/upload/01-incident-brief-NVX-INC-4821.md` | Markdown | The incident and the 11.4 mm/s vibration measurement |
| 2 | `demo-assets/pump-incident-demo/upload/02-safety-procedure-PROC-SAFE-118.pdf` | PDF with a real text layer | Restart rule, repair requirements, temporary measure. This is the file used for the visual citation preview. |
| 3 | `demo-assets/pump-incident-demo/upload/03-service-level-policy-SLA-PLATINUM-04.md` | Markdown | Restoration deadline and service credit |
| 4 | `demo-assets/pump-incident-demo/upload/04-spare-parts-inventory-NVX-2026-03.csv` | CSV | Stock levels, locations, transfer lead times |
| 5 | `demo-assets/pump-incident-demo/upload/06-unrelated-fleet-vehicle-policy-POL-FLEET-22.md` | Markdown | **Scoping control.** Deliberately unrelated. Must never support an incident answer. |
| 6 | `demo-assets/pump-incident-demo/upload/05-note-de-service-NOTE-SVC-77.md` | Markdown, French | Uploaded later, just before the French act |

Upload files 1 to 5 together in one drop. Upload file 6 separately in act 6.

Every extension above is inside the Knowledge dropzone's accepted list
(**PDF · TXT · MD · DOCX · CSV · JSON**) and inside the backend's accepted set.
`tools/validate_demo_kit.py` re-checks both lists against the current source.

### The exact identifiers

`NVX-INC-4821` · `NVX-PUMP-7742` · `SITE-AUR-02` · `PROC-SAFE-118` ·
`SLA-PLATINUM-04` · `SEAL-KIT-3309` · `DEPOT-AUR` · `HUB-LYS` ·
`WORKAROUND-GP-02` · `NOTE-SVC-77` · `GBX-5501` (decoy) · `POL-FLEET-22` (control)

---

## 5. Main script

Each act gives you: **navigation**, **what to say**, **what to type**, **expected
facts with their sources**, and a **pass/fail check**.

### Act 1 — Start with the work (1 minute)

**Navigate**

1. Sign in at `http://127.0.0.1:4210`.
2. Do not click anything else. Let the landing surface speak.

**Say**

> Agentium opens on the job, not on a dashboard. This is Ask. Everything else —
> knowledge, systems, execution history — is one click away, but none of it is a
> prerequisite for getting a useful answer.

3. Point at the left rail: **Ask**, **Knowledge**, **Build**, **Runs**.

**Pass / fail**

| Pass | Fail |
| --- | --- |
| The URL resolves to `/chat?mode=quick` and the composer is visible | You land on a dashboard or a catalog |
| The rail shows exactly four primary destinations | More or fewer primary destinations |

---

### Act 2 — Connect and verify one model (2 minutes)

**Navigate**

1. Open **Settings**. Either go to `/settings` directly, or open the **Account**
   button in the top bar and choose **Settings**.
2. The **Providers** tab is the default. Find the **Set up the model** card.
3. Choose your **Provider** in the dropdown.
4. Type the exact installed model name in **Default model**.
5. If the provider needs them, fill **API key**, **Endpoint**, **Deployment**.
   These fields appear only for the providers that require them.
6. Click **Validate and save**.

**Say**

> Nothing is saved until the model actually answers a live probe. The hint under
> the button says it plainly: *Nothing is saved when the test fails.* A ready state
> here means a real round trip succeeded, not that someone typed a name into a form.

7. Return to **Ask**. The readiness strip should read **Assistant ready**.

**Pass / fail**

| Pass | Fail |
| --- | --- |
| The save completes and the readiness strip says **Assistant ready** | The card saves an unverified model |
| A bad key or a stopped provider produces a readable message | A raw provider exception or stack trace appears on screen |

*If you want to show the failure path here, use the deliberate drill in section 7
instead of breaking a shared account.*

---

### Act 3 — Add the trusted knowledge (3 minutes)

**Navigate**

1. Click **Knowledge** in the left rail (`/knowledge`).
2. Click the dashed upload area (**Drop files here or click to browse**), or drag
   the files onto it.
3. Select these five files together:
   - `demo-assets/pump-incident-demo/upload/01-incident-brief-NVX-INC-4821.md`
   - `demo-assets/pump-incident-demo/upload/02-safety-procedure-PROC-SAFE-118.pdf`
   - `demo-assets/pump-incident-demo/upload/03-service-level-policy-SLA-PLATINUM-04.md`
   - `demo-assets/pump-incident-demo/upload/04-spare-parts-inventory-NVX-2026-03.csv`
   - `demo-assets/pump-incident-demo/upload/06-unrelated-fleet-vehicle-policy-POL-FLEET-22.md`
4. Watch the status panel move from **Processing 5 file(s)** to **5 file(s) ready**
   with the message *You can now ask a question grounded in these documents.*
5. Leave **Advanced options** closed for a business audience.

**Say**

> These are the four documents a field-service team actually uses, plus one
> deliberately irrelevant fleet policy. Agentium is not being asked to know about
> pumps. It is being asked to answer from these files and show which one it used.

**Pass / fail**

| Pass | Fail |
| --- | --- |
| All five files reach **ready** without manual repair | A file stalls, or the panel shows **Processing failed** |
| The PDF, the CSV and the Markdown files all ingest | Only some formats ingest |

*If a file fails, the panel offers a retry. Retry it once. If it fails twice, drop
that file from the demo and say so rather than working around it silently.*

---

### Act 4 — The grounded decision (5 minutes)

This is the centre of the demo.

**Navigate**

1. Click **Ask** in the left rail, or **Ask a question** from the Knowledge upload
   panel.
2. Click **New chat** so the conversation starts empty.
3. Click into the composer and type prompt **P1** exactly:

```text
For incident NVX-INC-4821 on pump NVX-PUMP-7742, can the pump be restarted now, which spare part is required, where is that part in stock, and by when must the repair be finished under SLA-PLATINUM-04?
```

4. Press **Enter**. Let the answer stream to the end — the composer re-enables when
   streaming is finished.

**Expected answer facts, and the source that must support each**

| # | Fact the answer must contain | Supporting source |
| --- | --- | --- |
| F1 | Measured drive-end vibration is **11.4 mm/s RMS** | `01-incident-brief-NVX-INC-4821.md` |
| F2 | Above **7.1 mm/s RMS** restart is prohibited, so the pump **must not be restarted** | `02-safety-procedure-PROC-SAFE-118.pdf` |
| F3 | The repair needs **SEAL-KIT-3309**, **two certified technicians**, **5.5 hours** | `02-safety-procedure-PROC-SAFE-118.pdf` |
| F4 | **SEAL-KIT-3309** is **0 at DEPOT-AUR**, **3 at HUB-LYS**, **6 hours** transfer | `04-spare-parts-inventory-NVX-2026-03.csv` |
| F5 | Opened **2026-03-02 07:10 UTC**; P1 restoration due **within 24 hours**, i.e. by **2026-03-03 07:10 UTC** | `01-incident-brief-...md` + `03-service-level-policy-...md` |
| F6 | Late restoration costs **EUR 6,500 per started 12-hour block**, capped at **EUR 39,000** | `03-service-level-policy-SLA-PLATINUM-04.md` |

**Say**

> No single file contains that answer. The measurement came from the incident
> brief, the rule that makes it a stop condition came from the procedure, the part
> location came from a spreadsheet, and the deadline came from the contract. That
> is the difference between a chatbot and a governed knowledge system.

**Now inspect the evidence**

5. Point at a bracketed citation marker in the answer text, for example `[2]`.
6. Click **Sources · n** under the answer to expand the source list, if it is not
   already open.
7. Click the citation marker. The matching source row highlights.
8. On the source row for the procedure, click **Preview source document**.
9. The PDF opens in a full-screen viewer. Scroll to section 1 and show the
   **7.1 mm/s RMS** row in the restart decision table. The text is selectable —
   select it on screen to prove the document is really rendered, not described.
10. Click **Close preview**.

**Pass / fail**

| Pass | Fail |
| --- | --- |
| At least four of F1–F6 are present and correct | The answer is generic or contradicts a source |
| The answer carries at least one citation, and the sources panel lists the real filenames | No citations, or citations that do not resolve |
| The preview opens the actual PDF and the cited text is visible | The preview is empty, or shows a different document |
| `POL-FLEET-22` is **not** cited | The fleet policy is cited for a pump question |

---

### Act 5 — Follow-up, exact reference, and honest refusal (2 minutes)

Stay in the same conversation.

**5a. Follow-up (conversation continuity)** — type prompt **P2** exactly:

```text
If that part cannot arrive before the deadline, which temporary measure is allowed, what are its limits, and does it stop the restoration clock?
```

| Expected fact | Source |
| --- | --- |
| F7 — **WORKAROUND-GP-02**, at most **48 hours**, at **60 percent of nominal flow**, needs a **level 3** reliability engineer's approval | `02-safety-procedure-PROC-SAFE-118.pdf` |
| F8 — A temporary measure **does not stop** the restoration clock | `03-service-level-policy-...md` + `02-safety-procedure-...pdf` |

**Say**

> Notice I never repeated the part number. It resolved "that part" from the
> previous turn, and it still cited its sources.

**5b. Exact-reference retrieval and scoping** — type prompt **P3** exactly:

```text
Show the inventory line for SEAL-KIT-3309 and the inventory line for GBX-5501. Which of the two is relevant to NVX-INC-4821, and why?
```

| Expected fact | Source |
| --- | --- |
| F4 — the SEAL-KIT-3309 stock lines | `04-spare-parts-inventory-NVX-2026-03.csv` |
| F10 — **GBX-5501** is a **conveyor gearbox** part, six on hand locally, **not relevant** to a pump incident | `04-spare-parts-inventory-NVX-2026-03.csv` |

**Say**

> The tempting wrong answer is the part that is in stock right here. It rejected it
> because the data says it belongs to a conveyor, not a pump. Exact identifiers are
> retrieved exactly.

**5c. Safe abstention** — type prompt **P4** exactly:

```text
What is the remaining manufacturer warranty period on NVX-PUMP-7742, and who is the warranty contact at the pump manufacturer?
```

**Say**

> Nothing in these five documents mentions a warranty. This is the single most
> important behaviour in the whole demonstration.

**Pass / fail for act 5**

| Pass | Fail |
| --- | --- |
| P2 resolves "that part" without the identifier being repeated | It asks which part you mean, or answers about the wrong part |
| P3 quotes both lines and rules GBX-5501 out | It recommends GBX-5501, or cannot find either line |
| P4 states the sources do not contain warranty information | It invents a period, a date or a contact name |

*The corpus is verified to contain no warranty text; `tools/validate_demo_kit.py`
fails if any uploaded file ever gains it.*

---

### Act 6 — English and French (2 minutes)

**Navigate**

1. Go to **Knowledge**.
2. Upload the French note:
   `demo-assets/pump-incident-demo/upload/05-note-de-service-NOTE-SVC-77.md`
3. Wait for **1 file(s) ready**.
4. Open the **Account** button in the top bar. Under **Language**, click **FR**.
   The interface switches live; nothing reloads and nothing is lost.
5. Go to **Demander** (Ask) and click **Nouveau chat**.
6. Type prompt **P5** exactly:

```text
Pour l'incident NVX-INC-4821, qui doit approuver la mesure temporaire WORKAROUND-GP-02 et dans quel délai l'approbation doit-elle être consignée ?
```

| Expected fact | Source |
| --- | --- |
| F9 — the level 3 reliability engineer for the region is **Yara Oduya**, and approval must be logged within **30 minutes** | `05-note-de-service-NOTE-SVC-77.md` (French) |
| F7 — the level 3 approval requirement itself | `02-safety-procedure-PROC-SAFE-118.pdf` (English) |

**Say**

> The question is French, the answer is French, the note is French, and the
> procedure behind it is English. English and French are both first-class here, in
> the interface and in the answers.

7. Switch back to **EN** the same way when you are done.

**Pass / fail**

| Pass | Fail |
| --- | --- |
| The interface switches without a reload and without losing the workspace | The switch reloads or drops context |
| The answer is in French | The answer is in English |
| It cites the French note, and may also cite the English procedure | It cites nothing, or cites the fleet policy |

---

### Act 7 — Failure and recovery (2 minutes)

See section 7 for the three safe ways to trigger a failure. Pick one before you
present; do not improvise on a shared account.

**Navigate**

1. With the failure condition active, in **Ask**, type prompt **P6** exactly:

```text
Repeat the restoration plan for NVX-INC-4821 as a numbered checklist a technician can follow on site.
```

2. Press **Enter**. An error card appears reading **The answer could not be
   completed**, with a readable cause such as *The model service is not responding.
   Try again in a moment.*

**Say**

> Three things just happened that matter more than the error itself. The question
> is still there — nobody has to retype it. No half-finished answer is being passed
> off as complete. And the next valid action is on the card, not in a manual.

3. Remove the failure condition (restart the local provider, or clear the throttle).
4. Click **Try again** on the error card.
5. The failed turn is replaced by a new, cited answer.

**Pass / fail**

| Pass | Fail |
| --- | --- |
| The error message is in plain language | A raw exception, a stack trace or a provider error code is shown |
| The typed question survives the failure | The input is cleared |
| Any partial output is labelled as partial | Partial text is presented as the answer |
| **Try again** produces a cited answer for the same question | Recovery needs a page reload or a retype |

---

### Act 8 — Turn it into a reusable System (3 minutes)

*Business-only audiences can stop after act 7.*

**Navigate**

1. Click **Build** in the left rail (`/systems`).
2. Click **New system**. The builder opens at `/systems/new`.
3. In **Objective**, set the name:

```text
Field Service Incident Advisor
```

4. In the same section, set the objective:

```text
Answer field-service questions about open pump incidents using only the Nordvane incident briefs, safety procedures, service-level policies and spare-parts inventory in this workspace, and always cite the source.
```

5. In **Context**, select the knowledge collection holding the uploaded files
   (`documents` unless you uploaded into a named collection).
6. Leave everything else collapsed. The builder shows only **Objective** and
   **Context** until you open **Advanced settings**.
7. Read the launch control at the top right. It is disabled until every gate is
   green, and its tooltip names the first gate that is not.
8. Click **CREATE SYSTEM** when it is enabled.

**Say**

> A System here is not a catalog card. Agentium refuses to create it while a
> required runtime is missing — you would see a **BLOCKED** badge naming the stub
> or unbound skills. Publishing something that cannot run is the failure mode this
> product is built to prevent.

**If readiness blocks you, that is a successful governance demonstration.** Show
the blocked state, say what it means, and move on. Do not bypass it.

**Pass / fail**

| Pass | Fail |
| --- | --- |
| The simple builder shows outcome and knowledge only, by default | Technical controls are mandatory up front |
| The launch control stays disabled until the gates pass | An unsatisfiable System can be created |
| Creating succeeds and opens the System view | A local draft warning appears — the API was unreachable, so say so |

---

### Act 9 — Inspect the execution evidence (2 minutes)

**Optional — depends on your local profile.** Only do the run step if this
deployment has a runnable capability bound. If it does not, show the Runs surface
and its history instead of forcing an execution.

**Navigate**

1. On a published System, click **Operator Runner**. Agentium opens
   `/systems/<id>/run`, shows the effective first-step input contract and prepares
   the required JSON fields. Fill every required value; **Execute published Flow**
   becomes available only when the System, ingress, published evidence, session and
   input are ready. A legacy zero-input System may show **Run now** instead.
2. Click **Runs** in the left rail (`/runs`).
3. If needed, filter with **All statuses**.
4. Click the newest row to open the Run.
5. Show the **Overview** tab: status, duration, and the run's identity.
6. Show the **Invocations** tab and open one **Skill trail** entry if one exists.
7. **Payloads** carries the raw input and outcome — show it to a technical audience
   only, and only with synthetic data on screen.

**Say**

> The business user sees an answer. The operator sees the execution behind it: what
> ran, how long it took, which skill was invoked, and where it failed if it failed.

**Pass / fail**

| Pass | Fail |
| --- | --- |
| The Runs list shows real executions with status and duration | The list is decorative or empty when a run just happened |
| A Run opens and its detail reflects the runtime | Detail is missing or contradicts the list |
| Missing required input is explained before execution and creates no Run | An empty payload is queued and later appears as a failed decision |

---

## 6. Technical-audience expansion

Run these only after the core demonstration has succeeded.

| Expansion | Where | What it proves |
| --- | --- | --- |
| Knowledge **Advanced options** | Knowledge header | Collections, semantic search and expert capture are secondary options, not first-run obstacles |
| Semantic search over the corpus | Knowledge → **Advanced options** → search | Search `SEAL-KIT-3309` and show the CSV chunk that comes back, with its score |
| Uncited-but-retrieved sources | Any answer's **Sources · n** panel | Rows marked *not cited* show what retrieval found but the model did not use — the panel does not flatter the answer |
| Builder **Advanced settings** | `/systems/new` | Capability, Skills, Policy and Launch sections, each with its own gate |
| Fail-closed readiness | Builder → **Skills** | The **BLOCKED · n stub · n unbound** badge, and the disabled launch control |
| Run payloads and skill invocations | `/runs/<id>` → **Invocations** | Real runtime evidence, per skill |
| Model administration | `/settings` | Provider list, live validation, and the routing source |

**Optional, flag-dependent — say so out loud before you click.** These surfaces
exist but are not part of the generic first-use promise, and several require a
workspace flag or a seeded profile:

| Surface | Condition |
| --- | --- |
| Knowledge capture | Requires the capture workspace flag |
| Experience Studio / Work launcher | Requires the experience flag and a deployed experience |
| Flow Builder and the Operator Runner | Advanced authoring; not the default mental model |
| Connectors | Show configured, healthy connectors only — never a catalog entry as if it were live |
| Hypervisor, Steering, outcome economics | Deferred by P3. Show only where real persisted data exists. |

If a flag-dependent surface is not enabled in your deployment, **skip it**. Do not
describe it as if you had shown it.

---

## 7. Failure and retry drill

Choose **one** method before the session. Never break a shared cloud account.

| Method | How | Best for |
| --- | --- | --- |
| **A. Stop the local provider** (recommended) | Stop your local model server (for example, quit Ollama), ask P6, restart it, click **Try again** | Local demos. Most realistic, fully reversible, and nothing outside your machine is touched. |
| **B. Interrupt reachability to a remote provider** | Disconnect the presenting machine's network, or block the provider host, ask P6, restore connectivity, click **Try again** | A remote or cloud provider you cannot stop. Only when nothing else on screen needs the network. |
| **C. Forced transport failure in the automated gate** | The P0.6 first-use Playwright journey aborts one `/api/v1/chat/stream` request, then retries | Rehearsal and technical evidence only. This is a test harness, not something to run during a live session. |

### Why you cannot simply save a broken configuration

You may be tempted to make **Settings** hold a broken model, key or endpoint so
that Ask fails later. **That does not work, by design.** Model setup is fail
closed: the save probes the provider live and is rejected when the probe fails,
which is exactly what the hint under the button says — *Nothing is saved when the
test fails.* An invalid model, key or endpoint never reaches the workspace, so it
can never produce a failure in Ask.

Say this out loud if someone asks. It is a stronger point than the drill itself:
the product will not let you create the broken state you were trying to fake.

Agentium's safe failure messages, none of which is a stack trace. Methods A to C
produce the first row; the others are listed so you recognise them if they appear:

| Situation | Message |
| --- | --- |
| Provider stopped or unreachable | *The model service is not responding. Try again in a moment.* |
| Bad credentials | *The model provider rejected its credentials. Update them in settings.* |
| Model name wrong | *The selected model is no longer available. Pick another one in settings.* |
| Throttled | *The model provider is throttling requests. Wait a moment, then try again.* |
| Timeout | *The answer took too long. Try again.* |

Each error card offers **Try again** and **Model settings**. **Technical details**
is a deliberate disclosure, not the default view — open it only for a technical
audience.

**Safety note for every method:** the failure must be something you introduced
outside Agentium and can undo in one action. Restore it immediately after the
drill and confirm **Assistant ready** in Ask before continuing. Never revoke a
shared key, and never change a setting you cannot put back.

---

## 8. Reset and rehearsal

### Full rehearsal, once, before the real session

Run the complete script end to end in a disposable workspace. Time it. Note which
of F1–F10 your model actually produces — model quality varies, and you should know
in advance which facts you can promise.

### Reset between sessions

| Goal | How |
| --- | --- |
| Clean conversation | **Ask** → **New chat**. Enough for a repeat demo in the same workspace. |
| Clean knowledge | **Knowledge** → open the collection → delete the kit documents, or delete the whole collection |
| Clean everything | Switch to a fresh demo workspace. Preferred for back-to-back customer sessions. |
| Clean Systems | **Build** → open the System → delete it, if you created one in act 8 |

### Re-verify the kit itself

From `demo-assets/pump-incident-demo/`:

```bash
python3 tools/generate_assets.py --check   # generated files have not drifted
python3 tools/validate_demo_kit.py         # identifiers, facts, sources, ROI
```

Both are offline and need only the Python standard library.

### If you edit the procedure PDF

Never edit the PDF. Edit
`demo-assets/pump-incident-demo/source/safety-procedure-PROC-SAFE-118.source.md`,
then run `python3 tools/generate_assets.py`. The generator is deterministic, so
`--check` will confirm whether the committed PDF matches its source.

---

## 9. Troubleshooting

| Symptom | Likely cause | What to do on stage |
| --- | --- | --- |
| Ask shows **Setup needed** or **Assistant unavailable** | No validated model for this workspace | Click **Set up the model**, complete act 2, return |
| Ask shows **Checking the model…** and stays there | Backend not reachable | Stop. Check the API is up. Do not ask questions into an unknown state. |
| Upload panel shows **Processing failed** | Unsupported file, or ingestion error | Use the retry action. If a second attempt fails, drop that file and say which fact you can no longer show. |
| A file uploads but is never cited | It was not retrieved for that question | Ask a question containing the file's exact identifier, for example `SEAL-KIT-3309` |
| The answer has no citations | Retrieval returned nothing, or the model ignored it | Re-ask with an exact identifier. If still uncited, say so — do not claim grounding you cannot show. |
| **Preview source document** opens nothing | The original file is no longer retrievable | Show the cited text in the sources panel instead, and note the preview issue honestly |
| The answer cites `POL-FLEET-22` | Scoping failure | Say it plainly: this is the control document and it should not have been used. This is a real finding, not a presentation problem. |
| The French answer comes back in English | Locale and answer language diverged | Re-ask in French in a **Nouveau chat**. Report it if it repeats. |
| **CREATE SYSTEM** stays disabled | A gate is unmet | Hover it: the tooltip names the first unmet gate. Open **Advanced settings** and show it. |
| A **BLOCKED · n stub · n unbound** badge appears | Required skills have no runtime | This is correct fail-closed behaviour. Demonstrate it; do not bypass it. |
| **Created as local draft (API unreachable)** | The backend rejected the creation | Say so. Do not present a local draft as a published System. |
| `/runs` is empty after a run | The run was not triggered, or this profile has no runnable capability | Use the Runs surface to show history instead. Mark the run step as not applicable here. |
| `validate_demo_kit.py` fails | A kit file was edited by hand | Read the FAIL lines; they name the file and the missing string |

---

## 10. Capability-to-demo coverage matrix

| Verified P0–P2 capability | Where this demo proves it | Evidence on screen |
| --- | --- | --- |
| Ask is the default home | Act 1 | The authenticated root resolves to `/chat?mode=quick` |
| Four primary destinations | Act 1 | Ask, Knowledge, Build, Runs in the rail |
| Model setup validated before saving | Act 2 | **Validate and save**; *Nothing is saved when the test fails* |
| Model readiness surfaced to the user | Act 2 | **Assistant ready** strip in Ask |
| Progressive Knowledge flow | Act 3 | Upload, processing, ready; **Advanced options** stays closed |
| Multi-format ingestion | Act 3 | PDF, CSV and Markdown all reach ready |
| Grounded answers over trusted knowledge | Act 4 | F1–F6 with citations |
| Cross-source synthesis | Act 4 | Four distinct sources behind one decision |
| Citations and source list | Act 4 | Citation markers and the **Sources · n** panel |
| Visual source preview | Act 4 | The PDF renders, with selectable cited text |
| Conversation continuity | Act 5a | "that part" resolves from the previous turn |
| Exact-reference retrieval | Act 5b | `SEAL-KIT-3309` and `GBX-5501` retrieved exactly |
| Correct retrieval scoping | Acts 4, 5b | `POL-FLEET-22` is never cited; `GBX-5501` is retrieved on request in P3 and then explicitly ruled out, never recommended for the repair |
| Safe abstention | Act 5c | No warranty answer is invented |
| English and French | Act 6 | Live locale switch; a French answer over a French source |
| Safe error language | Act 7 | Plain-language failure, no raw exception |
| Recovery preserving the task | Act 7 | **Try again** answers the same question, with citations |
| Simplified Build flow | Act 8 | Objective and Knowledge first; Advanced on demand |
| Fail-closed readiness and publishing | Act 8 | Disabled launch control; **BLOCKED** badge |
| Runs and Skill-invocation evidence | Act 9 | Run detail, **Invocations**, **Skill trail** |
| Activation telemetry | Not demonstrated | Privacy-safe funnel milestones exist but are not a user-facing surface |

**Intentionally not demonstrated** (P3 deferred, or deployment-specific): public
marketplace, skill certification, billing or subscriptions, one-click public web
app / embed / MCP publishing, hosted SaaS onboarding, broad connector catalogs,
Hypervisor and Steering economics without real persisted data.

---

## 11. ROI calculation walkthrough

Open `demo-assets/pump-incident-demo/roi/roi-model.md` on screen. Every number in
it is computed from `demo-assets/pump-incident-demo/roi/roi-assumptions.json`.

**Open with the boundary, not the number:**

> This is a **modeled** ROI, not a measured result. Every input is an assumption I
> chose and wrote down — none of them is a benchmark or an industry figure. I am
> showing you the arithmetic so you can replace the inputs with yours. If my
> assumptions are wrong, the model is wrong, and you will see exactly where.

### The three benefits

| # | Benefit | Formula | Result |
| --- | --- | --- | --- |
| 1 | Time saved locating procedure, policy and stock facts | `3600 incidents × (22 min × 0.35) / 60 × EUR 58/h` | EUR 26 796 |
| 2 | Service credits avoided on P1 restorations | `150 × 0.06 × 0.25 × EUR 6 500` | EUR 14 625 |
| 3 | Emergency freight avoided | `90 × 0.20 × EUR 1 250` | EUR 22 500 |

### The result

| Line | Value |
| --- | --- |
| Annual benefit | **EUR 63 921** |
| Year-one cost | **EUR 44 560** |
| Net value, year one | **EUR 19 361** |
| ROI, year one | **43.45 %** |
| Payback period | **8.37 months** |

```text
year_one_cost  = 28 000 implementation + 9 600 runtime + (120 h × 58) internal
               = EUR 44 560
net_value      = 63 921 - 44 560            = EUR 19 361
roi_percent    = 19 361 / 44 560 × 100      = 43.45 %
payback_months = 44 560 / (63 921 / 12)     = 8.37 months
```

### Why the evaluator should believe the shape, not the number

Say these out loud — they are what make the model defensible:

- The 22-minute baseline counts **document lookup only**, not travel or repair.
- The **35 percent** reduction is a scenario assumption chosen for this synthetic
  model. It is not a benchmark, not an industry figure, and not evidence of
  expected or measured Agentium performance. If the evaluator will not defend it,
  change it and re-run the model in front of them.
- Only **one** 12-hour credit block is counted per avoided breach, although
  `SLA-PLATINUM-04` allows up to six.
- Only **one expedited shipment in five** is assumed avoidable.
- Year-one cost carries the **full** implementation charge with no amortisation,
  plus a full year of runtime, plus the customer's own project hours.
- Faster production restart at the customer plant, reduced technician turnover,
  and all second-year benefit are **excluded**.

### Re-run it live with their numbers

```bash
# edit demo-assets/pump-incident-demo/roi/roi-assumptions.json
python3 tools/generate_assets.py
python3 tools/validate_demo_kit.py
```

The validator recomputes every line independently and fails if the report and the
assumptions disagree. Doing this in front of the evaluator is more persuasive than
the number itself.

---

## 12. Before / after scorecard

Hand this to the evaluator. It is theirs to fill in, not yours.

### A. What we do today

| Question | Today |
| --- | --- |
| How long does it take to answer "can this asset be restarted?" today? | ____ minutes |
| How many separate documents or systems are consulted? | ____ |
| Who has to be interrupted to confirm the answer? | ____ |
| How often is the wrong part dispatched or expedited? | ____ per year |
| How often is a service-level commitment missed for information reasons? | ____ per year |
| How is the basis for a decision recorded today? | ____ |

### B. What we saw in this demonstration

| Check | Target | Result |
| --- | --- | --- |
| Sign-in to a usable Ask composer | Immediate | ☐ pass ☐ fail |
| Model validated before saving | Ready state or actionable failure | ☐ pass ☐ fail |
| All five documents ingested | No manual repair | ☐ pass ☐ fail |
| First grounded answer | Under 45 seconds | ____ s ☐ pass ☐ fail |
| Expected facts present (F1–F6) | At least 4 of 6 | ____ / 6 |
| Answer carried citations | At least one, resolving to a real file | ☐ pass ☐ fail |
| Source preview opened the cited PDF | Cited text visible on screen | ☐ pass ☐ fail |
| Follow-up resolved without repeating the identifier | Yes | ☐ pass ☐ fail |
| Exact identifiers retrieved (`SEAL-KIT-3309`, `GBX-5501`) | Both | ☐ pass ☐ fail |
| Unrelated document excluded (`POL-FLEET-22`) | Never cited for the incident | ☐ pass ☐ fail |
| Decoy part ruled out (`GBX-5501`) | Retrieved when asked, then explicitly ruled out and never recommended for the repair | ☐ pass ☐ fail |
| Unanswerable question refused | No invented warranty | ☐ pass ☐ fail |
| French question answered in French | Yes | ☐ pass ☐ fail |
| Failure message was readable, no stack trace | Yes | ☐ pass ☐ fail |
| Retry recovered the same question with citations | Yes | ☐ pass ☐ fail |
| System creation respected readiness | Blocked or created correctly | ☐ pass ☐ fail |
| Run evidence inspectable | Yes / not applicable on this profile | ☐ pass ☐ fail ☐ n/a |

### C. What would have to be true for us to pilot this

| Question | Answer |
| --- | --- |
| Which document set would we start with? | ____ |
| Which model provider must be supported, and where must it run? | ____ |
| Which single use case would we measure? | ____ |
| What would success look like in 90 days? | ____ |
| Who owns the workspace, and who owns failures? | ____ |
| Which of our own numbers replace the ROI assumptions? | ____ |

---

## 13. Claim boundaries

### What this demonstration proves

- Agentium answers from **the documents you gave it**, and shows which ones.
- It **retrieves exact identifiers** and keeps irrelevant sources out.
- It **refuses** questions its sources cannot answer.
- It works in **English and French**, in the interface and in the answers.
- It **fails safely** and recovers without losing the user's task.
- It **refuses to publish** a System whose runtime cannot execute.
- It leaves **inspectable execution evidence**.

### What it does not prove, and must not be claimed

- **Nothing here is a measured customer result.** The ROI is a model built on
  editable assumptions. Say "modeled" every time you say the number.
- **The scenario data is synthetic.** Nordvane and Helioforge do not exist.
- **No product pricing was shown.** The euro amounts are domain data inside an
  invented service contract, not Agentium prices.
- **Answer quality depends on the model** you connected. A different model will
  produce a different wording and may miss a fact. That is why section 8 tells you
  to rehearse and note which facts your model actually produces.
- **This is one local profile.** It is not a certification of any production
  deployment, provider matrix, or scale.

### Never claim, on the basis of this demo

A public marketplace · skill certification · metered billing or subscriptions ·
hundreds of production-ready providers and plugins · every catalog connector as a
working integration · one-click public web app, embed or MCP publishing · a
turnkey hosted SaaS onboarding experience · broad production certification beyond
the documented local release profile.

The full scope-honesty rules are in
[`docs/agentium-demo-and-market-readiness-guide.md`](agentium-demo-and-market-readiness-guide.md),
section 6.

---

## 14. One-page cheat sheet

```text
PREFLIGHT   127.0.0.1:4210 loads · signed in · /settings model ready ·
            "Assistant ready" in Ask · 6 files present · validator green

ACT 1  1m   Land in Ask. Name: Ask / Knowledge / Build / Runs.
ACT 2  2m   Settings > Set up the model > Validate and save > "Assistant ready".
ACT 3  3m   Knowledge > drop files 01, 02, 03, 04, 06 > "5 file(s) ready".
ACT 4  5m   Ask > New chat > P1 > citations > Sources > Preview source document.
ACT 5  2m   P2 follow-up. P3 exact reference + decoy. P4 must refuse.
ACT 6  2m   Upload 05 > Account > Language FR > Nouveau chat > P5 > French answer.
ACT 7  2m   Break the provider > P6 > read the error > restore > Try again.
ACT 8  3m   Build > New system > objective + knowledge > CREATE SYSTEM.
ACT 9  2m   Operator Runner > complete required input > Execute > newest Run >
            Overview > Invocations. Legacy zero-input Systems may use Run now.

ROI         Annual EUR 63 921 · Cost EUR 44 560 · Net EUR 19 361 ·
            43.45 % · payback 8.37 months  — MODELED, not measured.

NEVER       Fake a flag-gated surface. Bypass a readiness block. Call the ROI
            a realized saving. Show a key, a URL or a stack trace.
```
