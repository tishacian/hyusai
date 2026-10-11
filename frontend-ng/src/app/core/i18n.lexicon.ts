/**
 * UI lexicon — the enforceable vocabulary of the product.
 *
 * One concept, one word, everywhere. This module is the single source of
 * truth for that word (EN and FR), for its one-line plain-language
 * definition, and for the words we refuse to let drift onto the screen.
 *
 * Three consumers, no copies:
 *
 * 1. `scripts/check-i18n.mjs` fails the build when a UI string uses a banned
 *    synonym or an internal term as a user-facing label. Vocabulary drift is
 *    a CI error, not a review opinion.
 * 2. `<ck-help id="concept.<id>" />` renders {@link LexiconEntry.definition}
 *    directly — the definition is never re-written in the help content YAML.
 *    See `help.service.ts`.
 * 3. Humans: this file is the answer to "what do we call this?".
 *
 * Deliberately dependency-free (no Angular import) so the guard script and
 * the unit spec can load it in plain Node.
 *
 * Adding a concept: see `./i18n/CONVENTION.md`.
 */

/** A canonical concept of the mental model. */
export interface LexiconEntry {
  /**
   * Stable concept id, kebab-case. Also the `<ck-help>` id, prefixed by
   * {@link CONCEPT_HELP_PREFIX} — `flow` → `concept.flow`.
   */
  readonly id: string;
  /** The English term. Capitalised as it should appear in a label. */
  readonly en: string;
  /** The French term. Identical to `en` when the term is a product noun. */
  readonly fr: string;
  /**
   * One line, plain language, no jargon, no nested clause. Rendered as-is by
   * `<ck-help>`; if it doesn't fit a tooltip in one breath, it's too long.
   */
  readonly definition: { readonly en: string; readonly fr: string };
  /**
   * Words that must never appear in a UI string. These are synonyms that
   * make the reader believe there are two concepts where there is one.
   * The guard rejects them outright.
   */
  readonly banned: readonly string[];
  /**
   * Internal jargon this term replaces on screen: API field names, node
   * kinds, raw runtime statuses. The guard rejects them in templates too —
   * they stay legitimate in code, in a `title`, or on a "Runtime details"
   * secondary line, never as the primary label.
   */
  readonly internal?: readonly string[];
  /**
   * English forms of the term that must not stand as words in a French
   * string. Only for a concept whose French term differs from the English
   * one: « Nouveau System » reads as a half-translated screen. The guard
   * ratchets them in the French dictionary and in the French definitions.
   */
  readonly untranslated?: readonly string[];
}

/** `<ck-help>` ids served from this lexicon rather than the help YAML. */
export const CONCEPT_HELP_PREFIX = 'concept.';

/**
 * The lexicon. Ordered by the mental model: the objects a user manipulates,
 * then the lifecycle words, then the flow anatomy, then the runtime words
 * that used to leak from the API.
 */
export const UI_LEXICON: readonly LexiconEntry[] = [
  {
    id: 'skill',
    en: 'Skill',
    fr: 'Skill',
    definition: {
      en: 'One unit of work the platform can run, with a defined input and output.',
      fr: "Une unité de travail que la plateforme sait exécuter, avec une entrée et une sortie définies.",
    },
    banned: [],
  },
  {
    id: 'capability',
    en: 'Capability',
    fr: 'Capability',
    definition: {
      en: 'A business outcome the platform can deliver, carried by one or more skills.',
      fr: "Un résultat métier que la plateforme sait produire, porté par une ou plusieurs skills.",
    },
    banned: [],
  },
  {
    // The wizard is designed to be read alongside a client's requirements
    // document, and names its sections. The acronym is the product's, so it
    // gets a definition rather than a ban — a reader with no such document
    // must still understand what is being asked of them.
    id: 'business-requirements',
    en: 'Business requirements document (BRD)',
    fr: "Document d'exigences métier (BRD)",
    definition: {
      en: 'The document where a client states the outcomes, requirements and decisions a system must cover.',
      fr: "Le document où un client énonce les résultats, les exigences et les décisions qu'un système doit couvrir.",
    },
    banned: [],
  },
  {
    id: 'system',
    en: 'System',
    fr: 'Système',
    definition: {
      en: 'A deployed assembly of a capability, a context and a policy, ready to run.',
      fr: "Un assemblage déployé d'une capability, d'un contexte et d'une politique, prêt à être exécuté.",
    },
    banned: [],
    untranslated: ['System', 'Systems'],
  },
  {
    // "Automation" is what the Create hub and Work call a System started by
    // a trigger rather than by a person; the French word is the full one.
    id: 'automation',
    en: 'Automation',
    fr: 'Automatisation',
    definition: {
      en: 'A system that starts from a trigger, lets an agent do the work and delivers an output.',
      fr: "Un système qui part d'un déclencheur, confie le travail à un agent et livre une sortie.",
    },
    banned: [],
    untranslated: ['automation', 'automations'],
  },
  {
    id: 'context',
    en: 'Context',
    fr: 'Contexte',
    definition: {
      en: 'The versioned data a system works with: its knowledge collections, memory and constraints, attached to every run.',
      fr: "Les données versionnées d'un système : ses collections, sa mémoire et ses contraintes, jointes à chaque exécution.",
    },
    banned: [],
  },
  {
    // The zone keeps its product name in French (« Knowledge » in the rail,
    // per the navigation mockups); running French text says « connaissances ».
    id: 'knowledge',
    en: 'Knowledge',
    fr: 'Knowledge',
    definition: {
      en: 'The documents, collections and expert input a system searches to ground its answers.',
      fr: "Les connaissances d'un workspace : documents, collections et apports d'experts qu'un système consulte pour fonder ses réponses.",
    },
    banned: [],
  },
  {
    id: 'suite',
    en: 'Suite',
    fr: 'Suite',
    definition: {
      en: 'A set of systems packaged, sold and deployed together.',
      fr: 'Un ensemble de systèmes packagés, vendus et déployés ensemble.',
    },
    banned: [],
  },
  {
    id: 'business-application',
    en: 'Business application',
    fr: 'Application métier',
    definition: {
      en: 'The interface teams use every day, assembled from published Systems and served on /work.',
      fr: "L'interface que les équipes utilisent au quotidien, assemblée à partir de systèmes publiés.",
    },
    banned: [],
    internal: ['ExperienceDraft'],
  },
  {
    // The space of business applications. A product noun in both languages,
    // like Cockpit: « Ouvrir dans Work ».
    id: 'work',
    en: 'Work',
    fr: 'Work',
    definition: {
      en: 'The space where teams use published business applications for their daily tasks, without engine jargon.',
      fr: "L'espace où les équipes utilisent les applications métier publiées pour leurs tâches, sans jargon technique.",
    },
    banned: [],
  },
  {
    // The human surface of a business application: where a person watches
    // the agent's run, decides at its gates and talks to it. "Desk" and
    // "Board" named the same screen during the PR to PO build-up and made it
    // read as three surfaces; the lexicon keeps one. A client's own "service
    // desk" (ITSD) is their business noun, allow-listed where it appears.
    id: 'studio',
    en: 'Studio',
    fr: 'Studio',
    definition: {
      en: "The screen where a person works with a business application's agent: its run, its gates, its conversation.",
      fr: "L'écran où une personne travaille avec l'agent d'une application métier : son exécution, ses portes, sa conversation.",
    },
    banned: ['desk', 'board'],
  },
  {
    // The other space: where authors, operators and governors work on the
    // Systems themselves. Docs once called this space "Studio" too; the
    // product name is the one the code has always carried (`ck-*`).
    id: 'cockpit',
    en: 'Cockpit',
    fr: 'Cockpit',
    definition: {
      en: 'The space where you build Systems, run and steer them, and govern them.',
      fr: 'L’espace où l’on construit les systèmes, les exécute, les pilote et les gouverne.',
    },
    banned: [],
  },
  {
    id: 'binding',
    en: 'Binding',
    fr: 'Liaison',
    definition: {
      en: 'A stable link from an app action to one published System version and its contract.',
      fr: "Le lien stable d'une action vers une version publiée d'un système et son contrat.",
    },
    banned: [],
    internal: ['SystemBinding'],
  },
  {
    id: 'run',
    en: 'Run',
    fr: 'Exécution',
    definition: {
      en: 'One execution of a system or a flow, with its input, its outcome and its trail.',
      fr: "Une exécution d'un système ou d'un flow, avec son entrée, son résultat et sa trace.",
    },
    banned: ['job', 'jobs'],
    untranslated: ['Run', 'Runs'],
  },
  {
    id: 'invocation',
    en: 'Invocation',
    fr: 'Invocation',
    definition: {
      en: 'One call to a skill during a run, with its input, output, cost and duration.',
      fr: 'Un appel à une skill pendant une exécution, avec son entrée, sa sortie, son coût et sa durée.',
    },
    banned: [],
  },
  {
    id: 'provenance',
    en: 'Provenance',
    fr: 'Provenance',
    definition: {
      en: 'Where a value or an answer comes from: its source document, the run that produced it, or who declared it.',
      fr: "D'où vient une valeur ou une réponse : son document source, l'exécution qui l'a produite ou la personne qui l'a déclarée.",
    },
    banned: [],
  },
  {
    id: 'flow',
    en: 'Flow',
    fr: 'Flow',
    definition: {
      en: 'The ordered graph of steps a system runs, from trigger to output.',
      fr: "Le graphe ordonné des étapes qu'un système exécute, du déclencheur à la sortie.",
    },
    banned: ['workflow', 'workflows', 'pipeline', 'pipelines'],
  },
  {
    id: 'draft',
    en: 'Draft',
    fr: 'Brouillon',
    definition: {
      en: 'A version you can still change; it never serves live traffic.',
      fr: 'Une version encore modifiable ; elle ne sert jamais le trafic réel.',
    },
    banned: [],
  },
  {
    id: 'published',
    en: 'Published',
    fr: 'Publié',
    definition: {
      en: 'The version that actually runs; changing it takes a new publication.',
      fr: "La version qui s'exécute réellement ; la modifier demande une nouvelle publication.",
    },
    banned: [],
  },
  {
    id: 'release',
    en: 'Release',
    fr: 'Release',
    definition: {
      en: 'An immutable snapshot of pages, bindings, access, languages and theme.',
      fr: 'Un instantané immuable des pages, liaisons, accès, langues et thème.',
    },
    banned: [],
  },
  {
    id: 'pilot',
    en: 'Pilot',
    fr: 'Pilote',
    definition: {
      en: 'A limited deployment of a release, before it serves everyone.',
      fr: "Un déploiement limité d'une release, avant qu'elle ne serve tout le monde.",
    },
    banned: [],
  },
  {
    id: 'in-service',
    en: 'In service',
    fr: 'En service',
    definition: {
      en: 'The release currently serving users on /work.',
      fr: 'La release qui sert actuellement les utilisateurs sur /work.',
    },
    banned: [],
  },
  {
    id: 'trigger',
    en: 'Trigger',
    fr: 'Déclencheur',
    definition: {
      en: 'What starts a run: a person, a schedule, or an incoming event.',
      fr: 'Ce qui démarre une exécution : une personne, une planification ou un événement entrant.',
    },
    banned: [],
  },
  {
    id: 'decision',
    en: 'Decision',
    fr: 'Décision',
    definition: {
      en: 'A point where the flow picks a branch, from data or from a human approval.',
      fr: "Un point où le flow choisit une branche, à partir de données ou d'une approbation humaine.",
    },
    banned: [],
  },
  {
    id: 'recommendation',
    en: 'Recommendation',
    fr: 'Recommandation',
    definition: {
      en: 'A result the platform proposes; a person decides whether to act on it.',
      fr: 'Un résultat que la plateforme propose ; une personne décide de le suivre ou non.',
    },
    // "advisory" is the internal word for this, and it reached the screen in
    // both languages ("Brouillon advisory", "ADS-B advisory only"). On screen
    // the concept is a recommendation; a non-binding datum is "consultatif" /
    // "for information only".
    banned: ['advisory'],
  },
  // --- Value: how Impact adds systems up ---------------------------------
  {
    id: 'portfolio',
    en: 'Portfolio',
    fr: 'Portefeuille',
    definition: {
      en: 'Every system and capability of the workspace, seen together to weigh their activity, cost and value.',
      fr: "L'ensemble des systèmes et capabilities du workspace, vus ensemble pour peser leur activité, leur coût et leur valeur.",
    },
    banned: [],
  },
  {
    id: 'register',
    en: 'Register',
    fr: 'Registre',
    definition: {
      en: 'The list of every system in the portfolio, one row each, with its activity and the value it declares.',
      fr: 'La liste de tous les systèmes du portefeuille, une ligne par système, avec son activité et la valeur qu’il déclare.',
    },
    banned: [],
  },
  {
    id: 'value-basis',
    en: 'Value basis',
    fr: 'Base de valeur',
    definition: {
      en: 'What one result of a capability is worth, in hours or money, declared by a named person so results can be added up.',
      fr: "Ce que vaut un résultat d'une capability, en heures ou en argent, déclaré par une personne nommée pour pouvoir l'additionner.",
    },
    banned: [],
  },
  {
    id: 'value-contract',
    en: 'Value contract',
    fr: 'Contrat de valeur',
    definition: {
      en: 'The target a system must reach and what one unit is worth, approved by its owner; the gap is measured, never typed in.',
      fr: "L'objectif qu'un système doit atteindre et ce que vaut une unité, approuvés par son responsable ; l'écart est mesuré, jamais saisi.",
    },
    banned: [],
  },
  {
    id: 'entry-point',
    en: 'Entry point',
    fr: "Point d'entrée",
    definition: {
      en: 'Where a flow takes the input it starts from.',
      fr: "L'endroit où un flow récupère l'entrée dont il part.",
    },
    banned: [],
    internal: ['ingress'],
  },
  {
    id: 'output',
    en: 'Output',
    fr: 'Sortie',
    definition: {
      en: 'Where a flow delivers its result once every step has run.',
      fr: 'Là où un flow livre son résultat une fois toutes les étapes exécutées.',
    },
    banned: [],
    internal: ['sink'],
  },
  {
    id: 'preset-inputs',
    en: 'Preset inputs',
    fr: 'Entrées prédéfinies',
    definition: {
      en: "Input values fixed in advance, so nobody retypes them at each run.",
      fr: "Des valeurs d'entrée fixées à l'avance, que personne ne ressaisit à chaque exécution.",
    },
    banned: [],
    internal: ['frozen_input', 'frozen input'],
  },
  {
    id: 'human-approval',
    en: 'Human approval',
    fr: 'Approbation humaine',
    definition: {
      en: 'A step where a person must approve before the run goes on.',
      fr: "Une étape où une personne doit approuver avant que l'exécution continue.",
    },
    banned: [],
    internal: ['HITL'],
  },
  {
    id: 'core-skill-wrapper',
    en: 'Wrap a core skill',
    fr: 'Encapsuler une skill du socle',
    definition: {
      en: "A skill that wraps one of the platform's built-in skills, with inputs you preset.",
      fr: "Une skill qui encapsule une skill fournie par la plateforme, avec des entrées que vous prédéfinissez.",
    },
    banned: [],
    internal: ['registry_call'],
  },
  {
    id: 'llm-prompt-skill',
    en: 'LLM prompt template',
    fr: 'Gabarit LLM',
    definition: {
      en: 'A skill whose work is a single prompt you write, sent to a language model.',
      fr: "Une skill dont le travail est un unique prompt que vous rédigez, envoyé à un modèle de langage.",
    },
    banned: [],
    internal: ['prompt_template'],
  },
  {
    id: 'runtime-status',
    en: 'Runtime status',
    fr: "État d'exécution",
    definition: {
      en: 'Whether a skill returns real results, a placeholder, or nothing yet.',
      fr: "Indique si une skill renvoie de vrais résultats, un substitut, ou rien pour l'instant.",
    },
    banned: [],
    internal: ['unbound', 'catalog_only', 'catalog only'],
  },
  {
    id: 'execution-mode',
    en: 'Execution mode',
    fr: "Mode d'exécution",
    definition: {
      en: 'How the engine walks the steps: as a graph, step by step, or in compatibility mode.',
      fr: "La façon dont le moteur parcourt les étapes : en graphe, pas à pas, ou en mode compatibilité.",
    },
    banned: [],
    internal: ['STRICT DAG', 'DAG · OVERLAY COMPAT', 'LEGACY · SEQUENTIAL'],
  },
];

const BY_ID = new Map(UI_LEXICON.map((entry) => [entry.id, entry]));

/** Look a concept up by id. */
export function lexiconEntry(id: string): LexiconEntry | null {
  return BY_ID.get(id) ?? null;
}

/** The canonical term for a concept in the given locale. */
export function lexiconTerm(id: string, locale: 'fr' | 'en'): string {
  const entry = BY_ID.get(id);
  if (!entry) return id;
  return locale === 'fr' ? entry.fr : entry.en;
}

/** The one-line definition for a concept in the given locale. */
export function lexiconDefinition(id: string, locale: 'fr' | 'en'): string {
  const entry = BY_ID.get(id);
  if (!entry) return '';
  return locale === 'fr' ? entry.definition.fr : entry.definition.en;
}

/**
 * Every forbidden word, with what to say instead. Consumed by the guard;
 * exported here so the rule and the vocabulary never live apart.
 */
export interface ForbiddenWord {
  readonly word: string;
  readonly conceptId: string;
  readonly kind: 'banned-synonym' | 'internal-jargon';
  readonly en: string;
  readonly fr: string;
}

export function forbiddenWords(): readonly ForbiddenWord[] {
  const out: ForbiddenWord[] = [];
  for (const entry of UI_LEXICON) {
    for (const word of entry.banned) {
      out.push({ word, conceptId: entry.id, kind: 'banned-synonym', en: entry.en, fr: entry.fr });
    }
    for (const word of entry.internal ?? []) {
      out.push({ word, conceptId: entry.id, kind: 'internal-jargon', en: entry.en, fr: entry.fr });
    }
  }
  return out;
}

/**
 * An English form of a term, left standing in a French string. Consumed by
 * the guard's French-term ratchet; see {@link LexiconEntry.untranslated}.
 */
export interface UntranslatedWord {
  readonly word: string;
  readonly conceptId: string;
  /** What the French string should say instead. */
  readonly fr: string;
}

export function untranslatedTerms(): readonly UntranslatedWord[] {
  const out: UntranslatedWord[] = [];
  for (const entry of UI_LEXICON) {
    for (const word of entry.untranslated ?? []) {
      out.push({ word, conceptId: entry.id, fr: entry.fr });
    }
  }
  return out;
}

/**
 * The English forms a French string still uses as words.
 *
 * - Case-insensitive: « le même run » is as English as « le même Run ».
 * - A word, not a fragment: letters, digits, `_`, `-` and `.` on either side
 *   make it part of something else (`Systèmes`, `run_id`, `dry-run`,
 *   `system.prompt`).
 * - `{placeholders}` and `` `code` `` are not copy: `{runs} Runs` counts the
 *   visible word once, never the placeholder name.
 *
 * Product names carrying the word are not exempted here on purpose — none
 * ships in French today; a future one goes to the guard's allowlist with
 * its reason, like any other exception.
 */
export function untranslatedInFrench(text: string): readonly UntranslatedWord[] {
  const copy = text.replace(/\{[^{}]*\}/g, ' ').replace(/`[^`]*`/g, ' ');
  return untranslatedTerms().filter(({ word }) =>
    new RegExp(`(?<![\\p{L}\\p{N}_.-])${word}(?![\\p{L}\\p{N}_-]|\\.\\p{L})`, 'iu').test(copy),
  );
}
