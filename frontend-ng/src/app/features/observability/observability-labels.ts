import type { I18nService } from '@app/core/i18n.service';

const legacyMessages: Record<string, string> = {
 'Draft changed; review it again': 'draft_changed',
 'The draft changed; reload before proposing a correction': 'draft_changed',
 'The draft or executor changed; prepare and review a new proposal': 'draft_changed',
 'The reviewed draft revision does not match': 'draft_changed',
 'The draft node differs from the executed node; test the draft first': 'draft_changed',
 'Open a server draft before proposing a correction': 'draft_required',
 'This historical or seeded executor cannot receive a template correction': 'unsupported_executor',
 'This node does not support a prompt template correction': 'unsupported_executor',
 'Review the current proposal before applying it': 'review_required',
 'Admin access required for the managed System': 'access_denied',
 'Collection ledger fingerprint; external model revisions and live retrieval are not immutable.': 'live_dependencies',
 'Corpus changed or became unavailable during the campaign.': 'corpus_changed',
 'Comparison could not continue. Review access and canonical Run status before retrying.': 'comparison_unavailable',
};

/** Translate platform codes, never user text, source passages or model output. */
export function observabilityText(i18n: Pick<I18nService, 't'>, category: string, value: unknown): string {
 const code = typeof value === 'string' ? legacyMessages[value] || value : '';
 const key = category === 'dimension' ? `observability.charts.dimension.${code}` : `observability.codes.${category}.${code}`;
 const translated = code ? i18n.t(key) : key;
 return translated !== key ? translated : i18n.t(`observability.codes.${category}.unknown`);
}

export function observabilityNumber(value: number | null | undefined, locale: string, digits = 0): string {
 return typeof value === 'number' && Number.isFinite(value)
  ? new Intl.NumberFormat(locale, {minimumFractionDigits: digits, maximumFractionDigits: digits}).format(value) : '—';
}
