import type { CkGlyphName } from '@app/shared/cockpit';
import type { WorkspaceMode } from '@app/core/workspace.service';

/** A projection that can be applied to a hierarchy object. */
export type ObjectLens = 'build' | 'operate' | 'steer' | 'govern';

/**
 * Primary rail destinations. Hypervisor is deliberately a Portfolio home,
 * not an object lens. ``CockpitLens`` remains as a compatibility alias while
 * workspaces that have not enabled axes v4 keep the five-lens behaviour.
 */
export type CockpitDestination = 'hypervisor' | ObjectLens;
export type CockpitLens = CockpitDestination;

export function isObjectLens(value: unknown): value is ObjectLens {
  return value === 'build' || value === 'operate' || value === 'steer' || value === 'govern';
}

export type AgentiumObjectType =
  | 'Workspace'
  | 'Capability'
  | 'System'
  | 'Skill'
  | 'SkillInvocation'
  | 'Workbench'
  | 'Run'
  | 'Knowledge'
  | 'Review Queue'
  | 'Connector'
  | 'Governance';

export type SurfaceScope = 'workspace' | 'capability' | 'system' | 'run' | 'admin' | 'public';
export type SurfaceStatus = 'canonical' | 'compatibility' | 'internal' | 'public-external' | 'deprecated';
export type SurfaceAudience = 'workspace-user' | 'admin' | 'external' | 'system';

export interface AgentiumSurfaceRoute {
  id: string;
  label: string;
  route: string;
  routeAliases?: string[];
  lens: CockpitLens;
  object: AgentiumObjectType;
  scope: SurfaceScope;
  apiPrefix: string;
  status: SurfaceStatus;
  audience: SurfaceAudience;
  description: string;
}

/**
 * UI surface manifest.
 *
 * This is the frontend source of truth for the mental model axis:
 * lens, object, scope and primary API surface. Route modules still own
 * lazy-loading, but chrome and governance diagnostics read from here.
 */
export const AGENTIUM_SURFACE_ROUTES: AgentiumSurfaceRoute[] = [
  {
    id: 'hypervisor',
    label: 'Hypervisor',
    route: '/hypervisor',
    lens: 'hypervisor',
    object: 'Review Queue',
    scope: 'workspace',
    apiPrefix: '/api/v1/hypervisor',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Portfolio balance sheet, recommendations and what-if decisions.',
  },
  {
    id: 'mission-room',
    label: 'Mission Room',
    route: '/hypervisor/mission-room/cockpit',
    routeAliases: ['/hypervisor/mission-room/:view'],
    lens: 'hypervisor',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/mission-room',
    status: 'canonical',
    audience: 'workspace-user',
    description:
      'Executive government cockpit for briefing, projects, open intelligence, map and recommendation actions.',
  },
  {
    id: 'systems',
    label: 'Systems',
    route: '/systems',
    lens: 'build',
    object: 'System',
    scope: 'workspace',
    apiPrefix: '/api/v1/systems',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'System catalogue, builder and system workbench entry points.',
  },
  {
    id: 'system-capture',
    label: 'Capture de connaissances',
    route: '/systems/:systemId/capture',
    lens: 'build',
    object: 'Workbench',
    scope: 'system',
    apiPrefix: '/api/v1/knowledge-capture',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Parcours de capture rattache au systeme.',
  },
  {
    id: 'capabilities',
    label: 'Capabilities',
    route: '/capabilities',
    lens: 'build',
    object: 'Capability',
    scope: 'workspace',
    apiPrefix: '/api/v1/capabilities',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Business capability catalogue.',
  },
  {
    id: 'skills',
    label: 'Skills',
    route: '/skills',
    lens: 'build',
    object: 'Skill',
    scope: 'workspace',
    apiPrefix: '/api/v1/skills',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Runtime skill registry and health.',
  },
  {
    id: 'knowledge',
    label: 'Knowledge',
    route: '/knowledge',
    lens: 'build',
    object: 'Knowledge',
    scope: 'workspace',
    apiPrefix: '/api/v1/documents',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Collections, documents, previews and vectorization jobs.',
  },
  {
    id: 'knowledge-capture',
    label: 'Capture de connaissances',
    route: '/knowledge/capture',
    lens: 'build',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/knowledge-capture',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Entree workspace pour preparer une capture de connaissances.',
  },
  {
    id: 'fse-reports',
    label: "Rapports d'intervention FSE",
    route: '/knowledge/interventions',
    lens: 'build',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/knowledge-capture',
    status: 'canonical',
    audience: 'workspace-user',
    description: "Capture contrainte pour les rapports d'intervention FSE (template systeme).",
  },
  {
    id: 'orchestration',
    label: 'Flow Builder',
    route: '/orchestration',
    lens: 'build',
    object: 'System',
    scope: 'workspace',
    apiPrefix: '/api/v1/systems',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Flow authoring surface for systems.',
  },
  {
    id: 'chat',
    label: 'Chat Workbench',
    route: '/chat',
    lens: 'operate',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/chat',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Synchronous chat surface with workspace and system context.',
  },
  {
    id: 'client360-pdr',
    label: 'Client360 PDR',
    route: '/client360',
    lens: 'operate',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/client360',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Explainable spare-parts potential, mail drafts and impact tracking for Andritz.',
  },
  {
    id: 'nawa-itsd',
    label: 'Nawa ITSD',
    route: '/nawa/itsd',
    routeAliases: ['/nawa/itsd/password-reset'],
    lens: 'operate',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/runs',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'IT automation use-case catalogue and the Password Reset simulation bench.',
  },
  {
    id: 'workspace-chat',
    label: 'Workspace Chat Focus',
    route: '/workspace/:slug/chat',
    lens: 'operate',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/chat',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Direct expanded workspace chat surface without the standard Agentium chrome.',
  },
  {
    id: 'runs',
    label: 'Runs',
    route: '/runs',
    lens: 'operate',
    object: 'Run',
    scope: 'workspace',
    apiPrefix: '/api/v1/runs',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Canonical runtime evidence and execution detail.',
  },
  {
    id: 'skill-invocations',
    label: 'Skill Invocations',
    route: '/runs/:runId/invocations/:invocationId',
    lens: 'operate',
    object: 'SkillInvocation',
    scope: 'run',
    apiPrefix: '/api/v1/runs',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'One concrete Skill execution inside its canonical parent Run.',
  },
  {
    id: 'observability',
    label: 'Observability',
    route: '/observability',
    lens: 'operate',
    object: 'Run',
    scope: 'workspace',
    apiPrefix: '/api/v1/telemetry',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Runtime health and operational metrics.',
  },
  {
    id: 'intelligence',
    label: 'Intelligence',
    route: '/intelligence',
    lens: 'operate',
    object: 'Run',
    scope: 'workspace',
    apiPrefix: '/api/v1/intelligence',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Continuous intelligence jobs and analysis.',
  },
  {
    id: 'tasks',
    label: 'Missions',
    route: '/tasks',
    lens: 'operate',
    object: 'Run',
    scope: 'workspace',
    apiPrefix: '/api/v1/tasks',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Task runner and long-running job surface.',
  },
  {
    id: 'steering',
    label: 'Control Plane',
    route: '/steering',
    lens: 'steer',
    object: 'Governance',
    scope: 'workspace',
    apiPrefix: '/api/v1/control-plane',
    status: 'canonical',
    audience: 'admin',
    description: 'Policies, levers and simulation controls.',
  },
  {
    id: 'contexts',
    label: 'Contexts',
    route: '/steering/contexts',
    lens: 'steer',
    object: 'Knowledge',
    scope: 'workspace',
    apiPrefix: '/api/v1/contexts',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Context objects bound to systems and runs.',
  },
  {
    id: 'review-queue',
    label: 'Review Queue',
    route: '/steering/review-queue',
    lens: 'steer',
    object: 'Review Queue',
    scope: 'workspace',
    apiPrefix: '/api/v1/evaluation',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Human review and quality decisions.',
  },
  {
    id: 'governance',
    label: 'Governance',
    route: '/governance',
    lens: 'govern',
    object: 'Governance',
    scope: 'admin',
    apiPrefix: '/api/v1/audit',
    status: 'canonical',
    audience: 'admin',
    description: 'Audit, access, canonical answers and platform governance.',
  },
  {
    id: 'surface-map',
    label: 'Surface Map',
    route: '/governance/surface-map',
    lens: 'govern',
    object: 'Governance',
    scope: 'admin',
    apiPrefix: '/api/v1/catalog',
    status: 'canonical',
    audience: 'admin',
    description: 'UI routes mapped to API endpoints and compatibility status.',
  },
  {
    id: 'workspace-blueprints',
    label: 'Workspace Blueprints',
    route: '/governance/blueprints',
    lens: 'govern',
    object: 'Workspace',
    scope: 'admin',
    apiPrefix: '/api/v1/blueprints',
    status: 'canonical',
    audience: 'admin',
    description: 'Export and apply workspace structure/configuration without users, secrets or raw data.',
  },
  {
    id: 'workspace-app-platform',
    label: 'Workspace Apps',
    route: '/governance/workspace-apps',
    lens: 'govern',
    object: 'Workspace',
    scope: 'admin',
    apiPrefix: '/api/v1/governance/workspace-apps',
    status: 'canonical',
    audience: 'admin',
    description: 'Content-addressed installation, upgrade, rollback and uninstall lifecycle for Workspace Apps.',
  },
  {
    id: 'apps',
    label: 'Apps',
    route: '/apps',
    lens: 'govern',
    object: 'Connector',
    scope: 'workspace',
    apiPrefix: '/api/v1/skills',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Catalogued app integrations and runtime availability.',
  },
  {
    id: 'resources',
    label: 'Resources',
    route: '/resources',
    lens: 'govern',
    object: 'Connector',
    scope: 'workspace',
    apiPrefix: '/api/v1/sftp',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Workspace resources and connector catalogue.',
  },
  {
    id: 'connectors',
    label: 'Connectors',
    route: '/connectors',
    lens: 'govern',
    object: 'Connector',
    scope: 'workspace',
    apiPrefix: '/api/v1/sftp',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Workspace-scoped connector catalogue and connector entry points.',
  },
  {
    id: 'secure-deposit',
    label: 'SFTP / Secure Deposit',
    route: '/connectors/sftp',
    lens: 'govern',
    object: 'Connector',
    scope: 'workspace',
    apiPrefix: '/api/v1/sftp',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'External intake links and workspace staging queue.',
  },
  {
    id: 'external-deposit',
    label: 'External Deposit Portal',
    route: '/deposit/:accessId',
    lens: 'govern',
    object: 'Connector',
    scope: 'public',
    apiPrefix: '/api/v1/deposit-links',
    status: 'public-external',
    audience: 'external',
    description: 'Dedicated upload/listing portal for non-Agentium external users.',
  },
  {
    id: 'sharepoint',
    label: 'SharePoint',
    route: '/connectors/sharepoint',
    lens: 'govern',
    object: 'Connector',
    scope: 'workspace',
    apiPrefix: '/api/v1/sharepoint',
    status: 'canonical',
    audience: 'admin',
    description: 'SharePoint connector configuration.',
  },
  {
    id: 'sap-hana',
    label: 'SAP HANA',
    route: '/connectors/sap-hana',
    lens: 'govern',
    object: 'Connector',
    scope: 'workspace',
    apiPrefix: '/api/v1/hana',
    status: 'canonical',
    audience: 'admin',
    description: 'SAP HANA Cloud connector configuration.',
  },
  {
    id: 'model-portal',
    label: 'Models & Providers',
    route: '/resources?tab=providers',
    lens: 'govern',
    object: 'Connector',
    scope: 'workspace',
    apiPrefix: '/api/v1/models',
    status: 'canonical',
    audience: 'admin',
    description: 'LLM providers and serving — housed under Resources.',
  },
  {
    id: 'presets',
    label: 'Presets',
    route: '/presets',
    lens: 'govern',
    object: 'Governance',
    scope: 'admin',
    apiPrefix: '/api/v1/presets',
    status: 'canonical',
    audience: 'admin',
    description: 'RAG, evaluation and workspace-default presets.',
  },
  {
    id: 'legacy-settings',
    label: 'Legacy Settings',
    route: '/settings/legacy',
    lens: 'govern',
    object: 'Governance',
    scope: 'admin',
    apiPrefix: '/api/v1/settings',
    status: 'compatibility',
    audience: 'admin',
    description: 'Compatibility proxy over presets.',
  },
  {
    id: 'workspace-admin',
    label: 'Workspace Settings',
    route: '/workspace/:slug',
    lens: 'govern',
    object: 'Workspace',
    scope: 'admin',
    apiPrefix: '/api/v1/auth',
    status: 'canonical',
    audience: 'admin',
    description: 'Workspace identity, members, IAM access and lifecycle controls.',
  },
  {
    id: 'account',
    label: 'Account',
    route: '/account',
    lens: 'govern',
    object: 'Workspace',
    scope: 'workspace',
    apiPrefix: '/api/v1/auth',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'User profile, password, MFA, sessions and account controls.',
  },
];

export type CockpitScopeType =
  | 'capability'
  | 'system'
  | 'skill'
  | 'knowledge'
  | 'flow'
  | 'run'
  | 'skill_invocation'
  | 'preset'
  | 'app'
  | 'connector'
  | 'context';

export type CockpitSectionKey =
  | 'systems'
  | 'capabilities'
  | 'skills'
  | 'knowledge'
  | 'flows'
  | 'runs'
  | 'observability'
  | 'intelligence'
  | 'missions'
  | 'levers'
  | 'contexts'
  | 'review'
  | 'audit'
  | 'workspace'
  | 'apps'
  | 'resources'
  | 'connectors'
  | 'presets';

export interface CockpitSection {
  key: CockpitSectionKey;
  label: string;
  glyph: CkGlyphName;
  surfaceId: string;
  route: string;
  matches?: string[];
  scopeType: CockpitScopeType;
  /** The target canvas consumes the routed hierarchy instead of going global. */
  ancestryAware: boolean;
}

export interface CockpitVerb {
  key: CockpitDestination;
  label: string;
  hint: string;
  glyph: CkGlyphName;
  primarySurfaceId: string;
  primaryRoute: string;
  matches: string[];
  sections?: CockpitSection[];
  /** Sections under axes v4; an empty list makes a destination Portfolio-only. */
  v4Sections?: CockpitSection[];
  /** Pre-Lot-3 section set, retained while the routed axes feature is gated. */
  legacySections?: CockpitSection[];
  hiddenInModes?: WorkspaceMode[];
}

export type HierarchyObjectType =
  | 'capability'
  | 'system'
  | 'run'
  | 'skill_invocation'
  | 'skill';

export interface NavigationAncestry {
  capabilityId: string | null;
  systemId: string | null;
  runId: string | null;
  skillInvocationId: string | null;
  skillRef: string | null;
}

export interface CockpitRouteContext extends NavigationAncestry {
  url: string;
  path: string;
  query: Readonly<Record<string, string>>;
  lens: CockpitLens;
  scope: CockpitSectionKey | null;
  selectedType: HierarchyObjectType | null;
  selectedRef: string | null;
}

export interface NavigationObjectUrlOptions extends Partial<NavigationAncestry> {
  lens?: CockpitLens | null;
  tab?: string | null;
  scope?: CockpitSectionKey | null;
}

export const BUSINESS_NAVIGATION_SURFACE_IDS = [
  'chat',
  'client360-pdr',
  'knowledge-capture',
  'fse-reports',
] as const;

const COCKPIT_LENSES = new Set<CockpitLens>([
  'hypervisor',
  'build',
  'operate',
  'steer',
  'govern',
]);

const HIERARCHY_SURFACE_IDS: Record<HierarchyObjectType, string> = {
  capability: 'capabilities',
  system: 'systems',
  run: 'runs',
  skill_invocation: 'skill-invocations',
  skill: 'skills',
};

const NAVIGATION_QUERY_KEYS = new Set([
  'lens',
  'scope',
  'tab',
  'facet',
  'focus',
  'capabilityId',
  'systemId',
  'runId',
  'skillRef',
]);

function pathOnly(value: string): string {
  const path = (value || '/').split('?')[0].split('#')[0] || '/';
  return path.startsWith('/') ? path : `/${path}`;
}

function decodedSegment(value: string | undefined): string | null {
  if (!value) return null;
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

function routeSegments(value: string): string[] {
  return pathOnly(value).split('/').filter(Boolean);
}

export function agentiumSurfaceById(surfaceId: string): AgentiumSurfaceRoute | null {
  return AGENTIUM_SURFACE_ROUTES.find((surface) => surface.id === surfaceId) ?? null;
}

export function agentiumSurfaceRoute(surfaceId: string): string {
  const surface = agentiumSurfaceById(surfaceId);
  if (!surface) throw new Error(`Unknown Agentium surface: ${surfaceId}`);
  return surface.route;
}

export function routeMatchesSurfacePattern(path: string, pattern: string): boolean {
  const actual = routeSegments(path);
  const expected = routeSegments(pattern);
  if (actual.length < expected.length) return false;
  return expected.every((segment, index) => segment.startsWith(':') || segment === actual[index]);
}

export function matchAgentiumSurface(value: string): AgentiumSurfaceRoute | null {
  const candidates = AGENTIUM_SURFACE_ROUTES.flatMap((surface) =>
    [surface.route, ...(surface.routeAliases ?? [])].map((pattern) => ({ surface, pattern })),
  ).sort((left, right) => {
    const leftSegments = routeSegments(left.pattern);
    const rightSegments = routeSegments(right.pattern);
    return (
      rightSegments.length - leftSegments.length ||
      rightSegments.filter((segment) => !segment.startsWith(':')).length -
        leftSegments.filter((segment) => !segment.startsWith(':')).length
    );
  });
  return candidates.find((candidate) => routeMatchesSurfacePattern(value, candidate.pattern))?.surface ?? null;
}

export function pathAllowedBySurfaceIds(value: string, surfaceIds: readonly string[]): boolean {
  return surfaceIds.some((surfaceId) => {
    const surface = agentiumSurfaceById(surfaceId);
    return Boolean(surface && [surface.route, ...(surface.routeAliases ?? [])].some((pattern) =>
      routeMatchesSurfacePattern(value, pattern),
    ));
  });
}

function surfaceRootsForLens(lens: CockpitLens): string[] {
  const roots = AGENTIUM_SURFACE_ROUTES
    .filter((surface) => surface.lens === lens && surface.audience !== 'external')
    .map((surface) => `/${routeSegments(surface.route)[0] ?? ''}`)
    .filter((route) => route !== '/');
  return [...new Set(roots)];
}

function section(
  key: CockpitSectionKey,
  label: string,
  glyph: CkGlyphName,
  surfaceId: string,
  scopeType: CockpitScopeType,
  matches?: string[],
  ancestryAware = false,
): CockpitSection {
  return {
    key,
    label,
    glyph,
    surfaceId,
    route: agentiumSurfaceRoute(surfaceId),
    scopeType,
    ancestryAware,
    ...(matches ? { matches } : {}),
  };
}

function hierarchySections(): CockpitSection[] {
  return [
    section('capabilities', 'Capabilities', 'focus', 'capabilities', 'capability', undefined, true),
    section('systems', 'Systems', 'cube', 'systems', 'system', undefined, true),
    section('runs', 'Runs', 'ledger', 'runs', 'run', undefined, true),
    section('skills', 'Skills', 'bolt', 'skills', 'skill', undefined, true),
  ];
}

export const COCKPIT_VERBS: CockpitVerb[] = [
  {
    key: 'hypervisor',
    label: 'Hypervisor',
    hint: 'Decide · balance sheet, outcomes, what-if',
    glyph: 'ledger',
    primarySurfaceId: 'hypervisor',
    primaryRoute: agentiumSurfaceRoute('hypervisor'),
    matches: surfaceRootsForLens('hypervisor'),
    sections: hierarchySections(),
    v4Sections: [],
    legacySections: [],
    hiddenInModes: ['builder'],
  },
  {
    key: 'build',
    label: 'Build',
    hint: 'Create Systems, Capabilities, Skills, Knowledge & Flows',
    glyph: 'cube',
    primarySurfaceId: 'systems',
    primaryRoute: agentiumSurfaceRoute('systems'),
    matches: surfaceRootsForLens('build'),
    sections: [
      ...hierarchySections(),
      section('knowledge', 'Knowledge', 'layers', 'knowledge', 'knowledge'),
      section('flows', 'Flow builder', 'flow', 'orchestration', 'flow', undefined, true),
    ],
    legacySections: [
      section('systems', 'Systems', 'cube', 'systems', 'system'),
      section('capabilities', 'Capabilities', 'focus', 'capabilities', 'capability'),
      section('skills', 'Skills', 'bolt', 'skills', 'skill'),
      section('knowledge', 'Knowledge', 'layers', 'knowledge', 'knowledge'),
      section('flows', 'Flow builder', 'flow', 'orchestration', 'flow'),
    ],
  },
  {
    key: 'operate',
    label: 'Operate',
    hint: 'Run Systems · runtime, runs, missions',
    glyph: 'telemetry',
    primarySurfaceId: 'runs',
    primaryRoute: agentiumSurfaceRoute('runs'),
    matches: surfaceRootsForLens('operate'),
    sections: [
      ...hierarchySections(),
      section('observability', 'Observability', 'telemetry', 'observability', 'system'),
      section('intelligence', 'Intelligence', 'pulse', 'intelligence', 'system'),
      section('missions', 'Missions', 'play', 'tasks', 'run'),
    ],
    legacySections: [
      section('runs', 'Runs', 'ledger', 'runs', 'run'),
      section('observability', 'Observability', 'telemetry', 'observability', 'system'),
      section('intelligence', 'Intelligence', 'pulse', 'intelligence', 'system'),
      section('missions', 'Missions', 'play', 'tasks', 'run'),
    ],
  },
  {
    key: 'steer',
    label: 'Steer',
    hint: 'Optimize Outcomes · levers, policies, simulations',
    glyph: 'sliders',
    primarySurfaceId: 'steering',
    primaryRoute: agentiumSurfaceRoute('steering'),
    matches: surfaceRootsForLens('steer'),
    sections: [
      ...hierarchySections(),
      section('levers', 'Control plane', 'sliders', 'steering', 'system'),
      section('contexts', 'Contexts', 'crosshair', 'contexts', 'context'),
      section('review', 'Review queue', 'warn', 'review-queue', 'system'),
    ],
    legacySections: [
      section('levers', 'Control plane', 'sliders', 'steering', 'system'),
      section('contexts', 'Contexts', 'crosshair', 'contexts', 'context'),
      section('review', 'Review queue', 'warn', 'review-queue', 'system'),
    ],
    hiddenInModes: ['builder'],
  },
  {
    key: 'govern',
    label: 'Govern',
    hint: 'Control · audit, apps, resources, presets',
    glyph: 'shield',
    primarySurfaceId: 'governance',
    primaryRoute: agentiumSurfaceRoute('governance'),
    matches: surfaceRootsForLens('govern'),
    sections: [
      ...hierarchySections(),
      section('audit', 'Governance', 'shield', 'governance', 'system'),
      // `/workspace` is the registry-owned entry alias resolved to the active slug.
      { ...section('workspace', 'Workspace settings', 'sliders', 'workspace-admin', 'system'), route: '/workspace' },
      section('apps', 'Apps', 'bolt', 'apps', 'app'),
      section('resources', 'Resources', 'orbit', 'resources', 'system'),
      section('connectors', 'Connectors', 'layers', 'connectors', 'connector'),
      section('presets', 'Presets', 'sliders', 'presets', 'preset'),
    ],
    legacySections: [
      section('audit', 'Governance', 'shield', 'governance', 'system'),
      { ...section('workspace', 'Workspace settings', 'sliders', 'workspace-admin', 'system'), route: '/workspace' },
      section('apps', 'Apps', 'bolt', 'apps', 'app'),
      section('resources', 'Resources', 'orbit', 'resources', 'system'),
      section('connectors', 'Connectors', 'layers', 'connectors', 'connector'),
      section('presets', 'Presets', 'sliders', 'presets', 'preset'),
    ],
  },
];

export const LENS_MATCHES: Record<CockpitLens, string[]> = COCKPIT_VERBS.reduce(
  (acc, verb) => ({ ...acc, [verb.key]: verb.matches }),
  {} as Record<CockpitLens, string[]>,
);

export function matchCockpitVerb(path: string): CockpitVerb | null {
  const surface = matchAgentiumSurface(path);
  if (surface) return COCKPIT_VERBS.find((verb) => verb.key === surface.lens) ?? null;
  return COCKPIT_VERBS.find((verb) => verb.matches.some((match) => {
    const normalized = pathOnly(path);
    return normalized === match || normalized.startsWith(match + '/');
  })) ?? null;
}

export function lensForNavigationUrl(value: string): CockpitLens {
  const context = navigationRouteContext(value);
  return context.lens;
}

export function navigationRouteContext(value: string, parseLens = true): CockpitRouteContext {
  const url = value || '/';
  const path = pathOnly(url);
  const rawQuery = url.includes('?') ? url.slice(url.indexOf('?') + 1).split('#')[0] : '';
  const params = new URLSearchParams(rawQuery);
  const query: Record<string, string> = {};
  for (const [key, item] of params.entries()) {
    if (NAVIGATION_QUERY_KEYS.has(key) && item) query[key] = item;
  }

  const segments = routeSegments(path);
  let selectedType: HierarchyObjectType | null = null;
  let selectedRef: string | null = null;
  if (
    segments[0] === 'runs'
    && segments[1]
    && segments[2] === 'invocations'
    && segments[3]
  ) {
    selectedType = 'skill_invocation';
    selectedRef = decodedSegment(segments[3]);
  } else if (segments[0] === 'capabilities' && segments[1]) {
    selectedType = 'capability';
    selectedRef = decodedSegment(segments[1]);
  } else if (segments[0] === 'systems' && segments[1] && segments[1] !== 'new') {
    selectedType = 'system';
    selectedRef = decodedSegment(segments[1]);
  } else if (segments[0] === 'runs' && segments[1]) {
    selectedType = 'run';
    selectedRef = decodedSegment(segments[1]);
  } else if (segments[0] === 'skills' && segments[1]) {
    selectedType = 'skill';
    selectedRef = decodedSegment(segments[1]);
  }

  const capabilityId = selectedType === 'capability'
    ? selectedRef
    : query['capabilityId'] || (path === '/capabilities' ? query['focus'] : null) || null;
  const systemId = selectedType === 'system' ? selectedRef : query['systemId'] || null;
  const runId = selectedType === 'run'
    ? selectedRef
    : selectedType === 'skill_invocation'
      ? decodedSegment(segments[1])
      : query['runId'] || null;
  const skillInvocationId = selectedType === 'skill_invocation' ? selectedRef : null;
  const skillRef = selectedType === 'skill' ? selectedRef : query['skillRef'] || null;
  const explicitLens = query['lens'];
  const matchedLens = matchAgentiumSurface(path)?.lens ?? 'build';
  const lens = parseLens && COCKPIT_LENSES.has(explicitLens as CockpitLens)
    ? explicitLens as CockpitLens
    : matchedLens;
  const rawScope = query['scope'];
  const scope = rawScope && COCKPIT_VERBS.some((verb) =>
    verb.sections?.some((item) => item.key === rawScope),
  ) ? rawScope as CockpitSectionKey : null;

  return {
    url,
    path,
    query,
    lens,
    scope,
    selectedType,
    selectedRef,
    capabilityId,
    systemId,
    runId,
    skillInvocationId,
    skillRef,
  };
}

function appendNavigationQuery(
  path: string,
  values: Readonly<Record<string, string | null | undefined>>,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (NAVIGATION_QUERY_KEYS.has(key) && value) params.set(key, value);
  }
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

function lensQueryForPath(path: string, lens: CockpitLens | null | undefined): CockpitLens | null {
  if (!lens) return null;
  return matchAgentiumSurface(path)?.lens === lens ? null : lens;
}

export function navigationObjectUrl(
  type: HierarchyObjectType,
  ref: string,
  options: NavigationObjectUrlOptions = {},
): string {
  if (type === 'skill_invocation') {
    if (!options.runId) {
      throw new Error('A SkillInvocation URL requires its canonical parent runId');
    }
    const path = `/runs/${encodeURIComponent(options.runId)}/invocations/${encodeURIComponent(ref)}`;
    return appendNavigationQuery(path, {
      lens: lensQueryForPath(path, options.lens),
      tab: options.tab,
      scope: options.scope,
      capabilityId: options.capabilityId,
      systemId: options.systemId,
    });
  }
  const path = `${agentiumSurfaceRoute(HIERARCHY_SURFACE_IDS[type])}/${encodeURIComponent(ref)}`;
  return appendNavigationQuery(path, {
    lens: lensQueryForPath(path, options.lens),
    tab: options.tab,
    scope: options.scope,
    capabilityId: type === 'capability' ? null : options.capabilityId,
    systemId: type === 'run' || type === 'skill' ? options.systemId : null,
    runId: type === 'skill' ? options.runId : null,
    // A selected hierarchy object is the leaf authority. Descendant refs
    // must never leak from the previous canvas into a global object jump.
    skillRef: null,
  });
}

export function navigationPortfolioUrl(
  lens?: CockpitLens | null,
  portfolioHomeOnly = false,
): string {
  const path = agentiumSurfaceRoute('hypervisor');
  if (portfolioHomeOnly) return path;
  return appendNavigationQuery(path, {
    lens: lensQueryForPath(path, lens),
  });
}

export function navigationLensUrl(
  currentUrl: string,
  targetLens: CockpitLens,
  fallbackRoute: string,
  verifiedAncestry?: NavigationAncestry,
  preserveExplicitLens = false,
): string {
  const context = navigationRouteContext(currentUrl);
  const ownsHierarchyContext = Boolean(
    context.selectedType ||
    context.capabilityId ||
    context.systemId ||
    context.runId ||
    context.skillInvocationId ||
    context.skillRef,
  );
  if (!ownsHierarchyContext) return fallbackRoute;
  const ancestry = verifiedAncestry ?? context;
  return appendNavigationQuery(context.path, {
    tab: context.query['tab'],
    facet: context.query['facet'],
    focus: context.query['focus'],
    scope: context.scope,
    lens: preserveExplicitLens ? targetLens : lensQueryForPath(context.path, targetLens),
    capabilityId: context.selectedType === 'capability' ? null : ancestry.capabilityId,
    systemId: context.selectedType === null || context.selectedType === 'run' || context.selectedType === 'skill_invocation' || context.selectedType === 'skill'
      ? ancestry.systemId
      : null,
    runId: context.selectedType === null || context.selectedType === 'skill'
      ? ancestry.runId
      : null,
    skillRef: context.selectedType === null ? ancestry.skillRef : null,
  });
}

/** What the Flow entry opens when no System is in scope: an unattached graph
 *  that belongs to nobody until it is promoted. */
export const SCRATCHPAD_SECTION_LABEL = 'Scratchpad';

export interface NavigationSectionNaming {
  /** Dictionary key, so a locale can still override the resolved wording. */
  i18nKey: string;
  /** Wording to use when the dictionary has no entry for `i18nKey`. */
  label: string;
}

/**
 * How a section should be named once its destination is known.
 *
 * Only the Flow entry is destination-dependent: it resolves either to a
 * System's graph or, with no System in scope, to the scratchpad. Naming it
 * from the catalog alone would promise a builder for a specific System and
 * then open an empty canvas, so the wording follows `resolvedUrl` — the exact
 * URL the rail is about to link to — rather than the static label.
 */
export function navigationSectionNaming(
  section: CockpitSection,
  resolvedUrl: string,
): NavigationSectionNaming {
  if (section.key === 'flows' && pathOnly(resolvedUrl) === section.route) {
    return { i18nKey: 'nav.flows.scratchpad', label: SCRATCHPAD_SECTION_LABEL };
  }
  return { i18nKey: `nav.${section.key}`, label: section.label };
}

/**
 * `flowSystemId` lets the caller carry a System the current URL no longer
 * proves — the last one the user actually opened — so leaving the hierarchy
 * for a flat list does not silently downgrade "Flow builder" to the
 * scratchpad. It is only consulted when the verified ancestry is empty.
 */
export function navigationScopeUrl(
  section: CockpitSection,
  ancestry: NavigationAncestry,
  lens: CockpitLens,
  flowSystemId: string | null = null,
): string {
  const flowTarget = section.key === 'flows'
    ? ancestry.systemId ?? flowSystemId
    : null;
  const path = flowTarget
    ? `/systems/${encodeURIComponent(flowTarget)}/flow`
    : section.route;
  return appendNavigationQuery(path, {
    lens: lensQueryForPath(path, lens),
    scope: section.key,
    capabilityId: ancestry.capabilityId,
    systemId: path.startsWith('/systems/') ? null : ancestry.systemId,
    runId: ancestry.runId,
    skillRef: ancestry.skillRef,
  });
}
