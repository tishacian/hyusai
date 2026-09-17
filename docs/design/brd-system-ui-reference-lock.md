# BRD → System authoring — reference lock

16 September 2026. Extend the existing Cockpit BRD import; no brand redesign.

| Decision | Reference | Adaptation |
|---|---|---|
| Keep Cockpit surfaces, typography and semantic tokens | Existing `brd-import.component.ts`, `cockpit-tokens.scss` | No NAWA theme modification or new palette |
| Compact, readable hierarchy and restrained separators | [Linear changelog](https://linear.app/changelog), Refero style `11d3e58a-87d7-4a9a-bbf5-720f4fd3ffc6` | Functional text, thin borders; do not import marketing headlines or a dark-only palette |
| Clear forms and explicit action | [shadcn UI](https://ui.shadcn.com), Refero style `c14c0a94-1037-449e-bf5b-4cb972656ac7` | Native labelled inputs, visible focus, one primary next action; retain Agentium tokens |
| Generation → review → editor | [n8n generation journey](https://refero.design/flows/9532) | Show operations and unresolved coverage before application; open the canonical Flow afterwards |
| Proposed is distinct from tested | Accepted R1 roadmap | Show uncovered requirements and not-run copy; no artificial completion percentages |
| Resume without browser document storage | Existing server-owned BRD and job records | URL retains document/job IDs; the API rechecks workspace rights |

The panel is a direct extension of the existing import dialog. Requirements use
source table/row identity, so repeated labels do not collapse separate rows.
Detailed contracts, prompts, mappings and cases are available before applying.
The original file can be downloaded. Publication remains in the existing Flow/
application lifecycle, outside the proposal's creation action.

Visual verification uses the actual Angular component with controlled fixture
responses. These images verify layout; they are not live PIH results or proof of
model generation. See the [capture evidence](../evidence/brd-system-ui-2026-09-16/README.md).

## Source indexing recovery — 16 September

The same Cockpit target governs the compact recovery panel in Knowledge and
SFTP. Existing `ck-surface`, `ck-fg-*`, `ck-warn` and `ck-btn-soft` tokens own
color, type and controls; no branding tokens change. The existing SFTP job list
supplies the operational hierarchy: state, cause, next action, then expandable
job identity and attempt history. Refero's craft-details focus/native-controls
rules supply keyboard behavior and a labelled native progress element. FR/EN
copy distinguishes failure, no job, unavailable status and dispatch pending.
A completed worker does not claim that every source or campaign has passed its
checks. This is an extension of the existing product surface, not a redesign.

The missing-original refinement follows the same state → cause → action hierarchy
and Refero `references/copywriting.md` error guidance: name the inaccessible file,
explain restoration before retry, keep raw storage keys in expandable details.
The diagnosis is server-owned and confirmed by storage, not guessed from an old
error string. Governed campaigns keep their own recovery instruction; a reader
cannot gain a retry control. No palette, layout or token-role change is needed.

## Run outcome card — 17 September

The existing Cockpit card remains the build target. Live Chrome QA on c19d30e8
found 40.8 px readout columns at a 390 px viewport, with text up to 96 px wide;
the full cost-calculation sentence also wrapped into five lines in a 70 px ledger
column. Revisited Refero Linear Changelog (11d3e58a-87d7-4a9a-bbf5-720f4fd3ffc6)
and shadcn UI (c14c0a94-1037-449e-bf5b-4cb972656ac7), plus copywriting guidance.

| Decision | Source | Preserved role |
|---|---|---|
| Fit readouts to available width, minimum 120 px; retain existing 18 px gap | Actual mobile overflow; existing Cockpit density | Readable figures and qualifications without hiding any metric |
| Short “Calculated / Calculé” beside each amount | Refero clarity rule; Linear compact technical notation | Basis remains visible; exact tariff evidence remains in the invocation audit |
| Keep existing tokens, fonts, surfaces and native details control | Existing Cockpit; shadcn functional components | No new palette, decoration, dependency or NAWA branding change |

This repairs the existing result card. No marketing imagery, new font family
or theme-specific palette from the external references is introduced.


## System Design — draft/publication boundary, 17 September

Target: the existing System graph summary and the Flow Builder publication
boundary, inspected live on PIH. Design used the published form projection while
the editor displayed draft r3. Reuse the existing graph list, native links and
Cockpit tokens; do not invent another graph renderer. State the draft revision
and published version together, following the locked n8n edit/review continuity
and existing publication controls. A failed draft read shows a retry, never a
fabricated RAG pipeline. Overview and historical Runs retain published identity.
FR/EN copy names the version distinction before the node list. No branding,
fonts, palette or new dependencies change.


The live 390 px capture on 18741f94 exposed the shared object header covering the
summary after scroll. Preserve the same identity/actions and Cockpit tokens;
return the header to document flow below 768 px or at viewport heights up to
600 px. Desktop sticky behavior remains. This follows the existing responsive
layout and accessibility target, without hiding actions or changing NAWA tokens.


## Capture publication → fresh conversation — 17 September

Reuse the existing publication success surface and ChatPanel, with a single next
question action and the actual collection name. The interview remains separate;
no prompt is submitted automatically. Existing Context creation supplies the
collection and the standard chat owns citations, Runs and source inspection.
The same small component serves both Capture surfaces. Keep Cockpit tokens and
published source actions; no NAWA branding changes or additional orchestration.

The new Capture action stays inside `adoption_experience_v1`, already used for
the pilot cohort. No new flag, workspace mutation or general client activation.
