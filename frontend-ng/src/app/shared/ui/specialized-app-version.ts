import type { WorkCatalogItem } from '@app/features/experience/work/work-catalog';

export type SpecializedApplication = 'client360' | 'itsd' | 'purchasing';

/** Published Experience identities, shared by the Work catalogue and native routes. */
const APPLICATION_SLUG: Record<SpecializedApplication, string> = {
  client360: 'client360',
  itsd: 'nawa',
  purchasing: 'pr-to-po',
};

export interface ApplicationRelease {
  id: string;
  number: number;
  channel: 'live' | 'pilot';
}

/** Only a complete, unambiguous release authorised by Work is version evidence. */
export function applicationRelease(
  application: SpecializedApplication,
  catalogue: readonly WorkCatalogItem[] | null | undefined,
): ApplicationRelease | null {
  if (!Array.isArray(catalogue)) return null;
  const matches = catalogue.filter((item) => item?.experience?.slug === APPLICATION_SLUG[application]);
  if (matches.length !== 1) return null;
  const { release, channel } = matches[0]!;
  if (typeof release?.id !== 'string' || !release.id.trim() || !Number.isSafeInteger(release.release_number)
    || (release.release_number ?? 0) < 1 || (channel !== 'live' && channel !== 'pilot')) return null;
  return { id: release.id, number: release.release_number!, channel };
}
