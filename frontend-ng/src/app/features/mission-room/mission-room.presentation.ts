/**
 * Last-mile presentation policy for the anonymised Octocity profile.
 *
 * Mission Room business components intentionally remain shared and unchanged.
 * API payloads are already presented by the backend, but a small number of
 * legacy static labels still live in component templates.  The extension host
 * applies this pure adapter to rendered text and accessibility attributes only.
 */

export const OCTOCITY_MISSION_ROOM_PROFILE = 'octocity_institutional_v1';
export const SENTINEL_MISSION_ROOM_PROFILE = 'sentinel_government_v1';

export const MISSION_ROOM_PRESENTATION_ATTRIBUTES = Object.freeze([
  'aria-label',
  'aria-description',
  'title',
  'placeholder',
  'alt',
] as const);

const OCTOCITY_LITERAL_REPLACEMENTS: ReadonlyArray<readonly [string, string]> = Object.freeze([
  ['sentinel_ci_aya_security_v1', 'octave_security_v1'],
  ['sentinel_ci_aya_v1', 'octave_mission_room_v1'],
  ['sentinel_ci', 'octocity'],
  ['sentinel-ci', 'octocity'],
  ['SENTINEL-CI', 'Octocity Mission Room'],
  ['Sentinel-CI', 'Octocity Mission Room'],
  ['aya_', 'octave_'],
  ['Monsieur le Vice Premier Ministre', 'Madame la Directrice de Coordination'],
  ['Vice Premier Ministre', 'Directrice de Coordination'],
  ['Vice-Premier Ministre', 'Directrice de Coordination'],
  ['Vice Premier minister', 'Coordination Director'],
  ['Republique de Côte d’Ivoire', 'Octocity Civic Grid'],
  ['République de Côte d’Ivoire', 'Octocity Civic Grid'],
  ["Republique de Cote d'Ivoire", 'Octocity Civic Grid'],
  ["République de Côte d'Ivoire", 'Octocity Civic Grid'],
  ['Côte d’Ivoire', 'Asteria'],
  ["Côte d'Ivoire", 'Asteria'],
  ["Cote d'Ivoire", 'Asteria'],
  ['Ivory Coast', 'Asteria'],
  ['Ambassadeur France', 'Emissaire Helion'],
  ['ambassadeur France', 'emissaire Helion'],
  ['Ambassadeur de France', "Emissaire d'Helion"],
  ['ambassadeur de France', "emissaire d'Helion"],
  ['ivoirienne', 'asterienne'],
  ['ivoirien', 'asterien'],
  ['BCEAO', 'Civic Reserve'],
  ['UEMOA', 'Civic Union'],
  ['XOF', 'OCU'],
  ['Franc CFA', 'Octocity Unit'],
  ['franc CFA', 'Octocity unit'],
  ['CFA', 'OCU'],
  ['Abidjan', 'Meridian'],
  ['Yamoussoukro', 'Civitas'],
  ['Bouaké', 'Borealis'],
  ['Bouake', 'Borealis'],
  ['Korhogo', 'Northgate'],
  ['Bouna', 'Eastwatch'],
  ['Kong', 'Ridgepoint'],
  ['San Pedro', 'Harbor West'],
  ['Vridi', 'Quai Meridian'],
  ['Nawa', 'Liora'],
  ['Soubre', 'Solenne'],
  ['Napié', 'Auralis'],
  ['Napie', 'Auralis'],
  ['CEDEAO', 'Alliance Aurora'],
  ['cedeao', 'alliance aurora'],
  ['FANCI', "Garde Civique d'Asteria"],
  ['Préfecture', 'Coordination territoriale'],
  ['préfecture', 'coordination territoriale'],
  ['Préfet', 'Coordinateur territorial'],
  ['Prefet', 'Coordinateur territorial'],
  ['préfet', 'coordinateur territorial'],
  ['prefet', 'coordinateur territorial'],
  ['Cacao', 'Bio-composites'],
  ['cacao', 'bio-composites'],
  ['Cocoa', 'Bio-composites'],
  ['cocoa', 'bio-composites'],
  ['Anacarde', 'Fibre solaire'],
  ['anacarde', 'fibre solaire'],
  ["Afrique de l'Ouest", 'Arc Atlantique'],
  ['West Africa', 'Atlantic Arc'],
  ['Sahel', 'Northern Belt'],
  ['Golfe de Guinee', 'Gulf of Meridian'],
  ['Gulf of Guinea', 'Gulf of Meridian'],
  ['Africa/Abidjan', 'UTC'],
]);

const OCTOCITY_FORBIDDEN_PATTERNS: ReadonlyArray<readonly [string, RegExp]> = Object.freeze([
  ['SENTINEL-CI', /SENTINEL-CI|Sentinel-CI/],
  ['AYA', /\bAYA\b|\bAya\b|\baya\b|aya_/],
  ['Vice Premier Ministre', /Vice[ -]Premier Ministre|Vice Premier minister|\bVPM\b/],
  ["Côte d'Ivoire", /Côte d[’']Ivoire|Cote d'Ivoire|Ivory Coast/],
  ['Ambassadeur France', /[Aa]mbassadeur(?: de)? France/],
  ['institutions monétaires Sentinel', /\bBCEAO\b|\bUEMOA\b|\bXOF\b|\bCFA\b/],
  ['géographies Sentinel', /\b(?:Abidjan|Yamoussoukro|Bouaké|Bouake|Korhogo|Bouna|Kong|San Pedro|Vridi|Nawa|Soubre|Napié|Napie)\b/],
  ['CEDEAO', /\bCEDEAO\b|\bcedeao\b/],
  ['FANCI', /\bFANCI\b/],
  ['Préfecture', /\bPréfecture\b|\bpréfecture\b|\bPréfet\b|\bpréfet\b|\bPrefet\b|\bprefet\b/],
  ['filières Sentinel', /\bCacao\b|\bcacao\b|\bCocoa\b|\bcocoa\b|\bAnacarde\b|\banacarde\b/],
  ['régions Sentinel', /Afrique de l'Ouest|West Africa|\bSahel\b|Golfe de Guinee|Gulf of Guinea/],
  ['CI', /\bCI\b/],
]);

/**
 * Mirror of OCTOCITY_FORBIDDEN_PATTERNS: the Octocity vocabulary that must
 * never surface in a non-Octocity workspace. Kept here so the Playwright
 * `cross_terms_absent` canary and the unit suite assert one single list.
 */
const SENTINEL_FORBIDDEN_PATTERNS: ReadonlyArray<readonly [string, RegExp]> = Object.freeze([
  ['Octocity', /Octocity/i],
  ['OCTAVE', /\bOCTAVE\b/i],
  ['Asteria', /\bAsteria\b/i],
  ['Meridian', /\bMeridian\b/i],
]);

export function presentMissionRoomText(profile: string | null, value: string): string {
  if (profile !== OCTOCITY_MISSION_ROOM_PROFILE || !value) return value;

  let presented = value;
  for (const [source, replacement] of OCTOCITY_LITERAL_REPLACEMENTS) {
    presented = presented.split(source).join(replacement);
  }
  return presented
    .replace(/\bAYA\b/g, 'OCTAVE')
    .replace(/\bAya\b/g, 'OCTAVE')
    .replace(/\baya\b/g, 'octave')
    .replace(/\bVPM\b/g, 'Coordination')
    // Unlike the legacy backend string pass, keep this token bounded so
    // words such as OCTOCITY or DECISION can never be corrupted.
    .replace(/\bCI\b/g, 'AS');
}

export function findOctocityForbiddenPresentationTerms(value: string): string[] {
  return OCTOCITY_FORBIDDEN_PATTERNS
    .filter(([, pattern]) => pattern.test(value))
    .map(([label]) => label);
}

export function findSentinelForbiddenPresentationTerms(value: string): string[] {
  return SENTINEL_FORBIDDEN_PATTERNS
    .filter(([, pattern]) => pattern.test(value))
    .map(([label]) => label);
}
