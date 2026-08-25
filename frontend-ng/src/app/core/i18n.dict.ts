/**
 * i18n dictionaries — aggregator.
 *
 * The dictionary lives in `./i18n/<domain>.dict.ts`, one module per UI
 * domain; this file only merges them and derives {@link I18nKey}. Nothing
 * but the domain registry below should ever be edited here — new keys go in
 * the domain module whose prefix they carry (see `./i18n/CONVENTION.md`).
 *
 * Two guarantees hold at compile time:
 *
 * * each domain module annotates its EN half as
 *   `Record<keyof typeof <DOMAIN>_FR, string>`, so a key added to one locale
 *   and forgotten in the other is a `tsc` error;
 * * {@link I18nKey} is the union of every key, so `i18n.t('typo.key')` is a
 *   `tsc` error at the call site.
 *
 * `npm run check:i18n` covers what the type system can't: keys filed under
 * the wrong domain, keys defined twice across domains, hard-coded strings in
 * templates, and banned synonyms from the UI lexicon.
 */

import { CAPTURE_EN, CAPTURE_FR } from './i18n/capture.dict';
import { CHAT_EN, CHAT_FR } from './i18n/chat.dict';
import { CHROME_EN, CHROME_FR } from './i18n/chrome.dict';
import { CLIENT360_EN, CLIENT360_FR } from './i18n/client360.dict';
import { COMMON_EN, COMMON_FR } from './i18n/common.dict';
import { CONTEXTS_EN, CONTEXTS_FR } from './i18n/contexts.dict';
import { DATA_EN, DATA_FR } from './i18n/data.dict';
import { DEPOSIT_EN, DEPOSIT_FR } from './i18n/deposit.dict';
import { EXPERIENCE_EN, EXPERIENCE_FR } from './i18n/experience.dict';
import { FLOW_EN, FLOW_FR } from './i18n/flow.dict';
import { GOVERNANCE_EN, GOVERNANCE_FR } from './i18n/governance.dict';
import { HYPERVISOR_EN, HYPERVISOR_FR } from './i18n/hypervisor.dict';
import { KNOWLEDGE_EN, KNOWLEDGE_FR } from './i18n/knowledge.dict';
import { MISSION_EN, MISSION_FR } from './i18n/mission.dict';
import { RESOURCES_EN, RESOURCES_FR } from './i18n/resources.dict';
import { RUNS_EN, RUNS_FR } from './i18n/runs.dict';
import { SETTINGS_EN, SETTINGS_FR } from './i18n/settings.dict';
import { SKILLS_EN, SKILLS_FR } from './i18n/skills.dict';
import { SYSTEMS_EN, SYSTEMS_FR } from './i18n/systems.dict';
import { TASKS_EN, TASKS_FR } from './i18n/tasks.dict';

/**
 * Domain registry — the single place that says which key prefixes belong to
 * which module. Read by `scripts/check-i18n.mjs` to reject a key filed in
 * the wrong module, which is how the split survives 1500 keys.
 */
export const I18N_DOMAINS = {
  common: { prefixes: ['common', 'state'], fr: COMMON_FR, en: COMMON_EN },
  chrome: {
    prefixes: ['titlebar', 'nav', 'account', 'auth', 'palette', 'workspace'],
    fr: CHROME_FR,
    en: CHROME_EN,
  },
  capture: { prefixes: ['capture'], fr: CAPTURE_FR, en: CAPTURE_EN },
  chat: { prefixes: ['chat'], fr: CHAT_FR, en: CHAT_EN },
  systems: { prefixes: ['systems'], fr: SYSTEMS_FR, en: SYSTEMS_EN },
  runs: { prefixes: ['runs'], fr: RUNS_FR, en: RUNS_EN },
  flow: { prefixes: ['flow'], fr: FLOW_FR, en: FLOW_EN },
  skills: { prefixes: ['skills', 'capabilities'], fr: SKILLS_FR, en: SKILLS_EN },
  client360: { prefixes: ['client360'], fr: CLIENT360_FR, en: CLIENT360_EN },
  mission: { prefixes: ['mission'], fr: MISSION_FR, en: MISSION_EN },
  hypervisor: {
    prefixes: ['hypervisor', 'steering'],
    fr: HYPERVISOR_FR,
    en: HYPERVISOR_EN,
  },
  deposit: { prefixes: ['deposit'], fr: DEPOSIT_FR, en: DEPOSIT_EN },
  experience: { prefixes: ['experience'], fr: EXPERIENCE_FR, en: EXPERIENCE_EN },
  knowledge: { prefixes: ['knowledge'], fr: KNOWLEDGE_FR, en: KNOWLEDGE_EN },
  contexts: { prefixes: ['contexts'], fr: CONTEXTS_FR, en: CONTEXTS_EN },
  data: { prefixes: ['data'], fr: DATA_FR, en: DATA_EN },
  governance: { prefixes: ['governance'], fr: GOVERNANCE_FR, en: GOVERNANCE_EN },
  settings: { prefixes: ['settings', 'presets'], fr: SETTINGS_FR, en: SETTINGS_EN },
  tasks: { prefixes: ['tasks'], fr: TASKS_FR, en: TASKS_EN },
  resources: {
    prefixes: ['resources', 'connectors', 'apps'],
    fr: RESOURCES_FR,
    en: RESOURCES_EN,
  },
} as const satisfies Record<
  string,
  { prefixes: readonly string[]; fr: Record<string, string>; en: Record<string, string> }
>;

export type I18nDomain = keyof typeof I18N_DOMAINS;

/** French dictionary — the hard fallback locale (see {@link I18nService}). */
export const FR_DICT = {
  ...COMMON_FR,
  ...CHROME_FR,
  ...CAPTURE_FR,
  ...CHAT_FR,
  ...SYSTEMS_FR,
  ...RUNS_FR,
  ...FLOW_FR,
  ...SKILLS_FR,
  ...CLIENT360_FR,
  ...MISSION_FR,
  ...HYPERVISOR_FR,
  ...DEPOSIT_FR,
  ...EXPERIENCE_FR,
  ...KNOWLEDGE_FR,
  ...CONTEXTS_FR,
  ...DATA_FR,
  ...GOVERNANCE_FR,
  ...SETTINGS_FR,
  ...TASKS_FR,
  ...RESOURCES_FR,
} as const satisfies Record<string, string>;

export type I18nKey = keyof typeof FR_DICT;

/** English dictionary — same keys as {@link FR_DICT}, enforced per domain. */
export const EN_DICT: Record<I18nKey, string> = {
  ...COMMON_EN,
  ...CHROME_EN,
  ...CAPTURE_EN,
  ...CHAT_EN,
  ...SYSTEMS_EN,
  ...RUNS_EN,
  ...FLOW_EN,
  ...SKILLS_EN,
  ...CLIENT360_EN,
  ...MISSION_EN,
  ...HYPERVISOR_EN,
  ...DEPOSIT_EN,
  ...EXPERIENCE_EN,
  ...KNOWLEDGE_EN,
  ...CONTEXTS_EN,
  ...DATA_EN,
  ...GOVERNANCE_EN,
  ...SETTINGS_EN,
  ...TASKS_EN,
  ...RESOURCES_EN,
};
