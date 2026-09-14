export interface VoiceCommandSettings {
  commands_enabled?: boolean;
  trigger_word?: string | null;
  command_packs?: string[] | null;
  stop_phrases?: unknown;
}

export type VoiceCommandSurface = 'chat' | 'knowledge_capture';

export type DetectedVoiceCommand =
  | 'stop'
  | 'pause'
  | 'resume'
  | 'cancel'
  | 'repeat'
  | 'rephrase'
  | 'next_question'
  | 'validate'
  | 'end_turn'
  | 'end_section';

export function detectVoiceCommand(
  rawText: string,
  settings: VoiceCommandSettings = {},
  surface: VoiceCommandSurface = 'chat',
): DetectedVoiceCommand | null {
  if (settings.commands_enabled === false) return null;
  let commandText = normalizeVoiceCommandText(rawText);
  const triggerWord =
    typeof settings.trigger_word === 'string' ? normalizeVoiceCommandText(settings.trigger_word) : '';
  const hasTrigger = !!triggerWord && (commandText === triggerWord || commandText.startsWith(`${triggerWord} `));
  if (hasTrigger) commandText = commandText.slice(triggerWord.length).trim();

  const genericCommandsEnabled = voiceCommandPackEnabled(settings, [
    'global_voice_v1',
    'generic',
    'fr_basic',
    'workspace',
  ]);
  if (isNaturalStopCommand(commandText, settings.stop_phrases, genericCommandsEnabled, hasTrigger)) return 'stop';
  if (!genericCommandsEnabled) return null;

  if (surface === 'knowledge_capture') {
    if (isEndSectionCommand(commandText, hasTrigger)) return 'end_section';
    if (isEndTurnCommand(commandText, hasTrigger)) return 'end_turn';
  }

  const words = commandText.split(/\s+/).filter(Boolean);
  if (!hasTrigger && words.length > 4) return null;

  if (['stop', 'arrete', 'arret', 'fin', 'termine'].includes(commandText)) return 'stop';
  if (surface !== 'chat') return null;
  if (['pause', 'mets en pause'].includes(commandText)) return 'pause';
  if (['reprends', 'reprendre', 'continue', 'relance'].includes(commandText)) return 'resume';
  if (['annule', 'annuler', 'cancel', 'efface'].includes(commandText)) return 'cancel';
  if (['repete', 'repeter', 'repeat'].includes(commandText)) return 'repeat';
  if (['reformule', 'reformuler', 'rephrase'].includes(commandText)) return 'rephrase';
  if (commandText === 'question suivante' || commandText === 'suivant') return 'next_question';
  if (['valider', 'valide', 'confirmer', 'confirme'].includes(commandText)) return 'validate';
  return null;
}

export function normalizeVoiceCommandText(value: string): string {
  return value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^\p{L}\p{N}\s'-]/gu, ' ')
    .replace(/['-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function stripCommandFillers(commandText: string): string {
  let value = commandText;
  for (let i = 0; i < 3; i += 1) {
    const next = value
      .replace(/^(?:ok|okay|bon|alors|donc|du coup|voila)\s+/u, '')
      .replace(/\s+(?:merci)$/u, '')
      .trim();
    if (next === value) break;
    value = next;
  }
  return value;
}

function wordCount(commandText: string): number {
  return commandText.split(/\s+/).filter(Boolean).length;
}

function isEndTurnCommand(commandText: string, hasTrigger: boolean): boolean {
  const core = stripCommandFillers(commandText);
  if (!core || (!hasTrigger && wordCount(core) > 6)) return false;
  return [
    /^tour suivant$/u,
    /^point suivant$/u,
    /^j ai termine ce point$/u,
  ].some((pattern) => pattern.test(core));
}

function isEndSectionCommand(commandText: string, hasTrigger: boolean): boolean {
  const core = stripCommandFillers(commandText);
  if (!core || (!hasTrigger && wordCount(core) > 6)) return false;
  return [
    /^section suivante$/u,
    /^on passe a la suite$/u,
    /^fin de (?:la )?section$/u,
  ].some((pattern) => pattern.test(core));
}

function isNaturalStopCommand(
  commandText: string,
  configuredPhrases: unknown = null,
  includeDefaultPhrases = true,
  hasTrigger = false,
): boolean {
  const core = stripCommandFillers(commandText);
  if (!core) return false;
  const customPhrases = Array.isArray(configuredPhrases)
    ? configuredPhrases
        .map((phrase) => normalizeVoiceCommandText(String(phrase)))
        .filter(Boolean)
    : [];
  if (customPhrases.some((phrase) => core === phrase)) return true;
  if (hasTrigger && customPhrases.some((phrase) => core.includes(phrase))) return true;
  if (!includeDefaultPhrases || (!hasTrigger && wordCount(core) > 8)) return false;
  return [
    /^on peut s arreter(?: la)?$/u,
    /^on peut arreter(?: la)?$/u,
    /^nous pouvons nous arreter(?: la)?$/u,
    /^on s arrete(?: la)?$/u,
    /^on arrete(?: la)?$/u,
    /^on va s arreter(?: la)?$/u,
    /^je vais m arreter(?: la)?$/u,
    /^c est bon\b.*\b(?:arreter|stop|termine|terminer|fini|fin)$/u,
    /^ca suffit$/u,
    /^cela suffit$/u,
    /^on a fini$/u,
    /^c est fini$/u,
    /^c est termine$/u,
    /^(?:c est )?(?:la )?fin de session$/u,
    /^tu peux t arreter$/u,
    /^tu peux couper$/u,
    /^on coupe$/u,
  ].some((pattern) => pattern.test(core));
}

function voiceCommandPackEnabled(settings: VoiceCommandSettings, accepted: string[]): boolean {
  const packs = Array.isArray(settings.command_packs)
    ? settings.command_packs.map((pack) => String(pack).trim().toLowerCase()).filter(Boolean)
    : [];
  if (packs.length === 0) return true;
  return accepted.some((name) => packs.includes(name));
}
