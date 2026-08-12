# i18n & lexicon convention

Everything a user reads comes from a key. Every key exists in FR and EN.
Every concept has exactly one word, and the guard enforces it.

Run the guard before you push: `npm run check:i18n` (from `frontend-ng/`).

## 1. Where a key lives

`src/app/core/i18n/<domain>.dict.ts` — one module per domain, two exports
(`<DOMAIN>_FR` and `<DOMAIN>_EN`). `src/app/core/i18n.dict.ts` only merges
them and declares which key prefixes each domain owns (`I18N_DOMAINS`).

| domain | prefixes | surface |
| --- | --- | --- |
| `common` | `common.` `state.` | shared verbs, empty and error states |
| `chrome` | `titlebar.` `nav.` `account.` `auth.` `palette.` `workspace.` | app shell |
| `capture` | `capture.` | knowledge capture (Le Fil) |
| `chat` | `chat.` | chat panel and overlay |
| `systems` | `systems.` | systems grid, view, templates |
| `runs` | `runs.` | runs list and detail |
| `flow` | `flow.` | flow builder |
| `skills` | `skills.` `capabilities.` | skills and capabilities |
| `client360` | `client360.` | client 360 |
| `mission` | `mission.` | mission room |
| `hypervisor` | `hypervisor.` `steering.` | hypervisor and steering |

The guard fails if a key sits in a module that doesn't own its prefix, or if
two modules define the same key (the merge would silently pick one). Need a
new domain? Add the module, then add its entry to `I18N_DOMAINS` — one place.

## 2. How a key is named

`<domain>.<surface>.<thing>` — lowercase, dot-separated, `snake_case` only
when the segment mirrors an API value (`runs.status.hitl_pending`).

- `runs.list.column.cost` — a column header on the runs list.
- `runs.status.failed` — mirrors the API's `failed`, so a lookup by value works.
- `common.refresh` — genuinely cross-surface; if only two screens use it, it
  isn't common, keep it in its domain.

Write EN as the reference wording, then the FR. Placeholders are `{name}`;
`{brand}` is filled in for free by the service, never hard-code the product
name.

## 3. Translating a string in a component

```ts
import { I18nService } from '@app/core/i18n.service';

export class RunsListComponent {
  readonly i18n = inject(I18nService);   // public: the template calls it
}
```

```html
{{ i18n.t('runs.list.column.cost') }}
[title]="i18n.t('runs.list.description')"
{{ i18n.t('runs.list.count', { count: total() }) }}
```

`t()` reads the `locale` signal, so every call site re-renders when the user
flips languages — no reload, no `OnPush` workaround needed. An unknown key
returns itself, which is how a typo shows up on screen instead of a blank.
`t()` accepts `I18nKey | string` — the `string` half is what lets the
API-mirroring call sites build a key at runtime, and it is also why a typo is
*not* a `tsc` error. `npm run check:i18n` covers it instead: every literal key
handed to `t()` must exist, because a missing key ships the dotted string
itself to the screen.

Build a key at runtime (`'runs.status.' + status`) only when the value comes
from the API, and fall back to the raw value when the lookup misses:

```ts
const label = this.i18n.t(`runs.status.${status}`);
return label === `runs.status.${status}` ? status : label;
```

## 4. Adding a concept to the lexicon

`src/app/core/i18n.lexicon.ts` is the vocabulary of the product: term EN,
term FR, a one-line plain-language definition, the synonyms we refuse, and
the internal jargon the term replaces on screen.

```ts
{
  id: 'entry-point',
  en: 'Entry point',
  fr: "Point d'entrée",
  definition: {
    en: 'Where a flow takes the input it starts from.',
    fr: "L'endroit où un flow récupère l'entrée dont il part.",
  },
  banned: [],              // synonyms that must never appear in a UI string
  internal: ['ingress'],   // API/engine term: fine in code, never a label
}
```

- `banned` — a word that makes the reader think there are two concepts where
  there is one (`workflow` for Flow, `job` for Run). The guard rejects it in
  any UI string.
- `internal` — a raw API field, node kind or runtime status. The guard rejects
  it in templates. It stays legitimate in code, in a `title`, or on a
  "Runtime details" secondary line: **the two-register rule** — plain word as
  the primary label, technical term one level down, never removed.
- The definition must fit a tooltip in one breath. It is the *only* copy of
  that wording: `ck-help` renders it, docs quote it, nobody rewrites it.

Adding a word to `banned`/`internal` will usually turn the guard red on
existing screens. That's the point — either fix them, or record them in
`scripts/i18n-allowlist.json` with a reason that says who will.

## 5. Wiring `ck-help` to a definition

`<ck-help id="concept.<lexicon-id>" />` resolves straight from the lexicon;
there is nothing to add to `backend/app/content/help_content.yaml`.

```html
<ck-page-frame [title]="i18n.t('runs.title')">
  <ck-help titleHelp id="concept.run" />
</ck-page-frame>
```

The rule: **the first occurrence of a lexicon term on a screen carries a
`ck-help`.** `ck-page-frame` has a `titleHelp` slot for the screen's main
concept; anywhere else, drop the tag next to the label.

The builder persona also sees the `internal` terms under "Technical term";
operator and executive only see the definition. Richer, screen-specific help
(user story, prerequisites, related actions) still lives in the backend YAML
under its own id — the two coexist, as on the runs list (`concept.run` for
the word, `runs.list` for the screen).

Note `ck-help` keeps its **own** language preference
(`localStorage.agentium.help.lang`), separate from the UI locale; it only
defaults to the UI locale the first time. Don't route its labels through
`i18n.t()` or content and chrome would disagree.

## 6. The guard

```
cd frontend-ng && npm run check:i18n        # ~3s
```

It fails on:

1. **FR/EN parity** — also caught by `tsc`, since each module types its EN
   half as `Record<keyof typeof <DOMAIN>_FR, string>`.
2. **Misfiled or duplicated keys** — wrong domain module, or defined twice.
3. **Navigation coverage** — every navigation catalog destination has its
   `nav.*` and `nav.hint.*` keys.
4. **Hard-coded French in a template** — the FR-in-the-markup smell.
   Expression identifiers, `class`/`style`/event bindings, icon names and
   control-flow heads are ignored; text nodes, interpolated string literals,
   `title`, `aria-label` and `placeholder` are not.

   Three probes, because accents alone are not enough. A whole screen once
   shipped in French the guard never saw, simply because it was typed
   without accents:

   | probe | catches | example |
   | --- | --- | --- |
   | accents | ordinary French | `Réponse à vérifier` |
   | elision | accent-free French that keeps its apostrophe | `Vue d'ensemble` |
   | function words | accent-free French with no apostrophe either | `Detail opportunite selectionnee` |

   The last two are the reason the guard is not a spell-checker. Only
   words with no English homograph are listed, and only function words —
   `avec`, `dans`, `pour`, `cette`, `votre`… A noun list would drift; a
   determiner list does not. Three words are deliberately excluded even
   though they are French: `sans` (it is in `font-sans`, present in every
   inline style), `plus` and `encore`. On this repo the three probes
   together produce no false positive; the one shape to watch for is a
   French proper noun in seeded content (`Côte d'Ivoire`), which belongs
   in the allowlist as data, not as a string to translate.

   **What still gets through**: a short French label made only of nouns —
   `Statut`, `Fiche client`, `Score` — has no accent, no elision and no
   function word, and no probe will ever see it without also flagging
   English. Reviewing a diff on a French-speaking team remains the only
   backstop for those. Keep labels in the dictionary from the first line
   of a new screen; retro-fitting is what leaves this residue.
5. **Lexicon violations** — a banned synonym or an internal term in a
   dictionary value or a template.
6. **A literal key `t()` cannot answer** — see §3. The type system can't do
   this one, and the symptom is a raw `flow.toolbar.state.hold` rendered
   where a label belongs.

Exceptions live in `frontend-ng/scripts/i18n-allowlist.json`, each with a
`reason`:

- `hardcodedText[path].max` is a **ratchet**: it may shrink, never grow. The
  guard prints the new number when a sweep lets you lower it, and asks you to
  delete the entry once the file is clean.
- `lexicon[path].words` allows specific words in one file — for a genuinely
  different object (a connector ingestion *job* is not a Run) or a pending
  rename that another work stream owns.

An allowlist entry without a real reason is how vocabulary drift comes back.
