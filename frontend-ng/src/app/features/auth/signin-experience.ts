/**
 * Public, pre-authentication presentation contract.
 *
 * New links select a presentation with the explicit `experience` query
 * parameter.  `workspace` is retained only as a declarative compatibility
 * alias for links that predate this contract; it never grants workspace
 * access and is not used by the component itself for branching.
 */

export const SIGNIN_EXPERIENCE_QUERY_PARAM = 'experience' as const;
export const LEGACY_SIGNIN_WORKSPACE_QUERY_PARAM = 'workspace' as const;
export const SIGNIN_DEMO_QUERY_PARAM = 'demo' as const;

export type SigninExperienceProfile = 'standard' | 'sentinel_government_v1';
export type SigninExperienceSource = 'explicit_profile' | 'legacy_workspace_alias' | 'default';

export interface SigninQueryParams {
  get(name: string): string | null;
}

export interface SigninExperiencePresentation {
  readonly profile: SigninExperienceProfile;
  readonly source: SigninExperienceSource;
  readonly securityBand: string | null;
  readonly eyebrow: string;
  readonly title: string;
  readonly subtitle: string;
  readonly sovereignTag: string | null;
  readonly submitLabel: string;
  readonly prefillEmail: string | null;
}

export interface SigninExperienceDefinition
  extends Omit<SigninExperiencePresentation, 'source' | 'prefillEmail'> {
  readonly legacyWorkspaceAliases: readonly string[];
  readonly demoEmail: string | null;
}

const STANDARD_SIGNIN: SigninExperienceDefinition = Object.freeze({
  profile: 'standard',
  legacyWorkspaceAliases: Object.freeze([]),
  securityBand: null,
  eyebrow: 'COCKPIT ACCESS',
  title: 'Sign in',
  subtitle: 'Operator authentication · single workspace session.',
  sovereignTag: null,
  submitLabel: 'SIGN IN',
  // Compatibility for the historical `?demo=true` URL, which prefilled this
  // address even when no workspace presentation was selected.
  demoEmail: 'vp.demo@sentinel-ci.local',
});

const SENTINEL_SIGNIN: SigninExperienceDefinition = Object.freeze({
  profile: 'sentinel_government_v1',
  legacyWorkspaceAliases: Object.freeze(['sentinel-ci']),
  securityBand:
    'Validation conformite Athea — chiffrement bout en bout, hebergement souverain Cote d\'Ivoire',
  eyebrow: 'ACCES SOUVERAIN',
  title: 'Hyperviseur souverain SENTINEL-CI',
  subtitle: 'Authentification executive · session workspace sentinel-ci.',
  sovereignTag: 'Cockpit souverain · République de Côte d\'Ivoire',
  submitLabel: 'CONNEXION VPM',
  demoEmail: 'vp.demo@sentinel-ci.local',
});

/** Ordered configuration registry; the default entry is intentionally first. */
export const SIGNIN_EXPERIENCE_DEFINITIONS: readonly SigninExperienceDefinition[] = Object.freeze([
  STANDARD_SIGNIN,
  SENTINEL_SIGNIN,
]);

export function resolveSigninExperience(
  params: SigninQueryParams,
): SigninExperiencePresentation {
  const requestedProfile = normalized(params.get(SIGNIN_EXPERIENCE_QUERY_PARAM));
  let source: SigninExperienceSource = 'default';
  let definition: SigninExperienceDefinition | undefined;

  if (requestedProfile) {
    definition = SIGNIN_EXPERIENCE_DEFINITIONS.find(
      (item) => item.profile === requestedProfile,
    );
    if (definition) source = 'explicit_profile';
  } else {
    const legacyWorkspace = normalized(params.get(LEGACY_SIGNIN_WORKSPACE_QUERY_PARAM));
    definition = SIGNIN_EXPERIENCE_DEFINITIONS.find(
      (item) => legacyWorkspace !== null && item.legacyWorkspaceAliases.includes(legacyWorkspace),
    );
    if (definition) source = 'legacy_workspace_alias';
  }

  const selected = definition || STANDARD_SIGNIN;
  const demo = params.get(SIGNIN_DEMO_QUERY_PARAM) === 'true';
  return Object.freeze({
    profile: selected.profile,
    source,
    securityBand: selected.securityBand,
    eyebrow: selected.eyebrow,
    title: selected.title,
    subtitle: selected.subtitle,
    sovereignTag: selected.sovereignTag,
    submitLabel: selected.submitLabel,
    prefillEmail: demo ? selected.demoEmail : null,
  });
}

function normalized(value: string | null): string | null {
  const result = value?.trim();
  return result || null;
}
