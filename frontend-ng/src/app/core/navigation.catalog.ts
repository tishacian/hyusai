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
  | 'Dataset'
  | 'Model'
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
    id: 'work',
    label: 'Work',
    route: '/work',
    lens: 'hypervisor',
    object: 'Workspace',
    scope: 'workspace',
    apiPrefix: '/api/v1/experience',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Published business applications. An RBAC space, never a cockpit verb.',
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
    id: 'data',
    label: 'Data',
    route: '/data',
    lens: 'build',
    object: 'Dataset',
    scope: 'workspace',
    apiPrefix: '/api/v1/datasets',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Tabular datasets, column profiles, transformations and lineage.',
  },
  {
    id: 'models',
    label: 'Models',
    route: '/models',
    lens: 'build',
    object: 'Model',
    scope: 'workspace',
    apiPrefix: '/api/v1/ml-models',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Trained models, their evidence, their versions and the one that serves.',
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
    id: 'create',
    label: 'Create',
    route: '/create',
    lens: 'build',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/experiences',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Studio hub: create a business application, a System or Knowledge.',
  },
  {
    id: 'create-apps',
    label: 'Business applications',
    route: '/create/apps',
    lens: 'build',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/experiences',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Inventory of business applications authored in Studio.',
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
    id: 'mcp',
    label: 'MCP',
    route: '/connectors/mcp',
    lens: 'govern',
    object: 'Connector',
    scope: 'workspace',
    apiPrefix: '/api/v1/mcp',
    status: 'canonical',
    audience: 'admin',
    description: 'Workspace MCP server registry (URL, token, tools/list).',
  },
  {
    id: 'model-portal',
    label: 'Models & Providers',
    route: '/resources?facet=providers',
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

/**
 * Parameterized or one-off destinations that the Router serves but that are
 * not chrome surfaces. L6.1: every Router path has a surface, a leaf, or a
 * named exemption (`navigation.routes.spec.ts`).
 */
export interface AgentiumSurfaceLeaf {
  id: string;
  parent: string;
  route: string;
  label: string;
}

export const AGENTIUM_SURFACE_LEAVES: AgentiumSurfaceLeaf[] = [
  { id: 'system-new', parent: 'systems', route: '/systems/new', label: 'New System' },
  { id: 'system-flow', parent: 'systems', route: '/systems/:systemId/flow', label: 'System Flow' },
  { id: 'system-run', parent: 'systems', route: '/systems/:systemId/run', label: 'System Run' },
  { id: 'capability-curation', parent: 'capabilities', route: '/capabilities/curation', label: 'Capability curation' },
  { id: 'connector-rpa-bridge', parent: 'connectors', route: '/connectors/rpa-bridge', label: 'RPA bridge' },
  { id: 'create-app-new', parent: 'create-apps', route: '/create/apps/new', label: 'New business application' },
  { id: 'create-app-edit', parent: 'create-apps', route: '/create/apps/:appId', label: 'Studio editor' },
  { id: 'create-preview', parent: 'create', route: '/create/preview', label: 'Studio preview' },
  { id: 'workspace-app-unavailable', parent: 'hypervisor', route: '/workspace-app-unavailable', label: 'Workspace app unavailable' },
  { id: 'workspace-app-repair', parent: 'hypervisor', route: '/workspace-app-repair', label: 'Workspace app repair' },
  { id: 'help-guide', parent: 'work', route: '/help/:guideId', label: 'Help guide' },
  { id: 'work-getting-started', parent: 'work', route: '/work/getting-started', label: 'Getting started' },
  { id: 'work-pr-to-po', parent: 'work', route: '/work/pr-to-po', label: 'PR to PO Studio' },
  { id: 'work-page', parent: 'work', route: '/work/:slug/:pageId', label: 'Work page' },
  { id: 'connector-models-redirect', parent: 'resources', route: '/connectors/models', label: 'Models & providers redirect' },
  { id: 'governance-audit', parent: 'governance', route: '/governance/audit', label: 'Audit' },
  { id: 'governance-experiences', parent: 'governance', route: '/governance/experiences', label: 'Experience governance' },
  { id: 'governance-access', parent: 'governance', route: '/governance/access', label: 'Access' },
  { id: 'governance-chat-history', parent: 'governance', route: '/governance/chat-history', label: 'Chat history' },
  { id: 'governance-canonical-answers', parent: 'governance', route: '/governance/canonical-answers', label: 'Canonical answers' },
  { id: 'observability-quality', parent: 'observability', route: '/observability/quality', label: 'Quality' },
  { id: 'observability-performance', parent: 'observability', route: '/observability/performance', label: 'Performance' },
  { id: 'observability-traces', parent: 'observability', route: '/observability/traces', label: 'Traces (compat)' },
  { id: 'preset-evaluation', parent: 'presets', route: '/presets/evaluation', label: 'Evaluation preset' },
  { id: 'system-capture-page', parent: 'systems', route: '/systems/:systemId/capture', label: 'System capture' },
  { id: 'knowledge-doc', parent: 'knowledge', route: '/knowledge/:kbId', label: 'Knowledge collection' },
  { id: 'data-doc', parent: 'data', route: '/data/:datasetId', label: 'Dataset' },
  { id: 'model-doc', parent: 'models', route: '/models/:modelId', label: 'Model' },
  { id: 'context-doc', parent: 'contexts', route: '/steering/contexts/:contextId', label: 'Context' },
  { id: 'preset-doc', parent: 'presets', route: '/presets/:presetId', label: 'Preset' },
  { id: 'mission-room-agenda', parent: 'mission-room', route: '/hypervisor/mission-room/agenda', label: 'Mission Room agenda' },
  { id: 'mission-room-monitor', parent: 'mission-room', route: '/hypervisor/mission-room/monitor', label: 'Mission Room monitor' },
  { id: 'workspace-list', parent: 'workspace-admin', route: '/workspace', label: 'Workspace picker' },
  { id: 'workspace-chat-page', parent: 'workspace-chat', route: '/workspace/:slug/chat', label: 'Workspace chat' },
  { id: 'workspace-chat-knowledge', parent: 'workspace-admin', route: '/workspace/:slug/chat-knowledge', label: 'Chat knowledge settings' },
  { id: 'auth-signin', parent: 'account', route: '/auth/signin', label: 'Sign in' },
];

export type CockpitScopeType =
  | 'surface'
  | 'capability'
  | 'system'
  | 'skill'
  | 'knowledge'
  | 'dataset'
  | 'model'
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
  | 'data'
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
  | 'presets'
  | 'business_apps'
  | 'integrations';

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
  facet?: string | null;
  doc?: string | null;
  scope?: CockpitSectionKey | null;
}

export type NavLinkInput =
  | {
      type: HierarchyObjectType;
      ref: string;
      lens?: CockpitLens | null;
      facet?: string | null;
    }
  | {
      surface: string;
      lens?: CockpitLens | null;
      facet?: string | null;
    }
  | {
      leaf: string;
      ref?: string;
      params?: Record<string, string>;
      lens?: CockpitLens | null;
      facet?: string | null;
    }
  | {
      facet: string;
      capabilityId?: string | null;
    };

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
  'doc',
  'capabilityId',
  'systemId',
  'runId',
  'skillRef',
]);

const LEAF_PARAM = /:([A-Za-z][A-Za-z0-9]*)/g;

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

export function agentiumLeafById(leafId: string): AgentiumSurfaceLeaf | null {
  return AGENTIUM_SURFACE_LEAVES.find((leaf) => leaf.id === leafId) ?? null;
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

/**
 * The data plane is one entry in the Build menu, not two. Datasets and
 * models are a single lineage (a model is fitted on a dataset and scores
 * into another) and land in the platform the same way — as what a System's
 * runs produced and, once published, as a Skill. `/data` and `/models` stay
 * distinct routes so deep links hold; the rail paints the entry active on
 * both.
 */
function dataPlaneSection(): CockpitSection {
  return section('data', 'Data & Models', 'table', 'data', 'dataset', ['/data', '/models']);
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
    sections: [],
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
      section('systems', 'Systems', 'cube', 'systems', 'system', undefined, true),
      section('capabilities', 'Capabilities', 'focus', 'capabilities', 'capability', undefined, true),
      section('skills', 'Skills', 'bolt', 'skills', 'skill', undefined, true),
      section('knowledge', 'Knowledge', 'layers', 'knowledge', 'knowledge'),
      dataPlaneSection(),
      section('flows', 'Flow builder', 'flow', 'orchestration', 'flow', undefined, true),
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
      section('runs', 'Runs', 'ledger', 'runs', 'surface'),
      section('observability', 'Observability', 'telemetry', 'observability', 'surface'),
      section('intelligence', 'Intelligence', 'pulse', 'intelligence', 'surface'),
      section('missions', 'Missions', 'play', 'tasks', 'surface'),
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
      section('levers', 'Control plane', 'sliders', 'steering', 'surface'),
      section('contexts', 'Contexts', 'crosshair', 'contexts', 'context'),
      section('review', 'Review queue', 'warn', 'review-queue', 'surface'),
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
      section('audit', 'Governance', 'shield', 'governance', 'surface'),
      // `/workspace` is the registry-owned entry alias resolved to the active slug.
      { ...section('workspace', 'Workspace settings', 'sliders', 'workspace-admin', 'surface'), route: '/workspace' },
      section('apps', 'Apps', 'bolt', 'apps', 'app'),
      section('resources', 'Resources', 'orbit', 'resources', 'surface'),
      section('connectors', 'Connectors', 'layers', 'connectors', 'connector'),
      section('presets', 'Presets', 'sliders', 'presets', 'preset'),
    ],
  },
];

/**
 * Standard primary navigation: four task-led destinations.
 *
 * The rail names what a workspace member wants to do, not the cockpit lens
 * that owns the screen. Hypervisor, Steering, Governance, Skills,
 * Capabilities, Apps, Connectors, Resources and Models keep their routes and
 * their deep links; they are simply no longer primary destinations. The five
 * cockpit verbs above still drive the advanced surfaces and the mini rail.
 */
export type PrimaryNavKey = 'ask' | 'knowledge' | 'build' | 'runs';

export interface PrimaryNavItem {
  key: PrimaryNavKey;
  glyph: CkGlyphName;
  /** Destination when no workspace flag moves it. */
  route: string;
  /** Destination when Experience Studio is enabled. */
  studioRoute?: string;
  /** Query the destination carries. Works before a workspace slug is known. */
  query?: Readonly<Record<string, string>>;
  /** Path roots that paint this entry active, descendants included. */
  matches: readonly string[];
}

/** Canonical Ask home. `mode=quick` selects the simple grounded-question view. */
export const ASK_HOME_QUERY: Readonly<Record<string, string>> = { mode: 'quick' };
export const ASK_HOME_ROUTE = `${agentiumSurfaceRoute('chat')}?mode=quick`;

export const PRIMARY_NAVIGATION: readonly PrimaryNavItem[] = [
  {
    key: 'ask',
    glyph: 'focus',
    route: agentiumSurfaceRoute('chat'),
    query: ASK_HOME_QUERY,
    matches: [agentiumSurfaceRoute('chat')],
  },
  {
    key: 'knowledge',
    glyph: 'layers',
    route: agentiumSurfaceRoute('knowledge'),
    matches: [agentiumSurfaceRoute('knowledge')],
  },
  {
    key: 'build',
    glyph: 'cube',
    route: agentiumSurfaceRoute('systems'),
    studioRoute: agentiumSurfaceRoute('create'),
    matches: [agentiumSurfaceRoute('systems'), agentiumSurfaceRoute('create')],
  },
  {
    key: 'runs',
    glyph: 'ledger',
    route: agentiumSurfaceRoute('runs'),
    matches: [agentiumSurfaceRoute('runs')],
  },
];

export function primaryNavRoute(
  item: PrimaryNavItem,
  flags: { experienceStudio?: boolean } = {},
): string {
  return flags.experienceStudio && item.studioRoute ? item.studioRoute : item.route;
}

/** Route-based active state: a destination owns its descendants. */
export function primaryNavActive(item: PrimaryNavItem, url: string): boolean {
  const path = pathOnly(url);
  return item.matches.some((match) => path === match || path.startsWith(`${match}/`));
}

const CREATE_STUDIO_SECTION = section(
  'business_apps',
  'Business application',
  'orbit',
  'create-apps',
  'app',
);

export const LENS_MATCHES: Record<CockpitLens, string[]> = COCKPIT_VERBS.reduce(
  (acc, verb) => ({ ...acc, [verb.key]: verb.matches }),
  {} as Record<CockpitLens, string[]>,
);

export function cockpitVerbSections(
  verb: CockpitVerb,
  flags: { experienceStudio?: boolean } = {},
): CockpitSection[] {
  const sections = verb.sections ?? [];
  if (verb.key === 'build' && flags.experienceStudio) {
    return [CREATE_STUDIO_SECTION, ...sections];
  }
  return sections;
}

export type ObjectFacetHost =
  | 'system'
  | 'capability'
  | 'run'
  | 'skill'
  | 'skill_invocation';

export interface ObjectFacet {
  id: string;
  i18nKey: string;
  glyph: CkGlyphName;
}

const SYSTEM_OBJECT_FACETS: readonly ObjectFacet[] = [
  { id: 'overview', i18nKey: 'nav.facet.overview', glyph: 'cube' },
  { id: 'runs', i18nKey: 'nav.runs', glyph: 'ledger' },
  { id: 'design', i18nKey: 'systems.view.tab.design', glyph: 'flow' },
  { id: 'context', i18nKey: 'systems.view.tab.context', glyph: 'layers' },
];

/** Object type × lens → facets. Source for `?facet=`, `ck-tabs`, and the sommaire branch (D7). */
export const OBJECT_FACETS: Record<
  ObjectFacetHost,
  Partial<Record<ObjectLens | 'any', readonly ObjectFacet[]>>
> = {
  system: { any: SYSTEM_OBJECT_FACETS },
  capability: {
    any: [
      { id: 'overview', i18nKey: 'nav.facet.overview', glyph: 'focus' },
      { id: 'systems', i18nKey: 'nav.systems', glyph: 'cube' },
      { id: 'outcomes', i18nKey: 'nav.facet.outcomes', glyph: 'chart' },
      { id: 'policies', i18nKey: 'nav.facet.policies', glyph: 'shield' },
    ],
  },
  run: {
    any: [
      { id: 'overview', i18nKey: 'nav.facet.overview', glyph: 'ledger' },
      { id: 'invocations', i18nKey: 'nav.facet.invocations', glyph: 'bolt' },
    ],
  },
  skill: {
    any: [
      { id: 'overview', i18nKey: 'nav.facet.overview', glyph: 'bolt' },
      { id: 'invocations', i18nKey: 'nav.facet.invocations', glyph: 'play' },
      { id: 'spec', i18nKey: 'nav.facet.spec', glyph: 'layers' },
      { id: 'knowledge', i18nKey: 'nav.knowledge', glyph: 'layers' },
    ],
  },
  skill_invocation: {
    any: [
      { id: 'overview', i18nKey: 'nav.facet.overview', glyph: 'bolt' },
      { id: 'io', i18nKey: 'nav.facet.io', glyph: 'table' },
      { id: 'runtime', i18nKey: 'nav.facet.runtime', glyph: 'telemetry' },
    ],
  },
};

export function objectFacetsFor(host: ObjectFacetHost, lens: ObjectLens): readonly ObjectFacet[] {
  const byLens = OBJECT_FACETS[host];
  return byLens[lens] ?? byLens.any ?? [];
}

export const HYPERVISOR_FACETS: readonly ObjectFacet[] = [
  { id: 'synthese', i18nKey: 'nav.facet.synthese', glyph: 'ledger' },
  { id: 'registre', i18nKey: 'nav.facet.registre', glyph: 'table' },
  { id: 'couts', i18nKey: 'nav.facet.couts', glyph: 'chart' },
  { id: 'bases', i18nKey: 'nav.facet.bases', glyph: 'sliders' },
  { id: 'decisions', i18nKey: 'nav.facet.decisions', glyph: 'focus' },
  { id: 'journal', i18nKey: 'nav.facet.journal', glyph: 'pulse' },
];

export type HypervisorFacetId = (typeof HYPERVISOR_FACETS)[number]['id'];

export function isHypervisorFacet(value: string | null | undefined): value is HypervisorFacetId {
  return HYPERVISOR_FACETS.some((facet) => facet.id === value);
}

export function systemFacetForChild(child: HierarchyObjectType | null): string | null {
  if (child === 'run' || child === 'skill_invocation') return 'runs';
  if (child === 'skill') return 'design';
  return null;
}

export function navigationZoneSurfaceUrl(section: CockpitSection, lens: CockpitLens): string {
  return appendNavigationQuery(section.route, {
    lens: lensQueryForPath(section.route, lens),
  });
}

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
  const tabAlias = params.get('tab');
  if (!query['facet'] && tabAlias) query['facet'] = tabAlias;
  const capabilityAlias = params.get('capability_id');
  if (!query['capabilityId'] && capabilityAlias) query['capabilityId'] = capabilityAlias;
  const systemAlias = params.get('system_id');
  if (!query['systemId'] && systemAlias) query['systemId'] = systemAlias;

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

function queryFromRoute(route: string): Record<string, string> {
  if (!route.includes('?')) return {};
  const params = new URLSearchParams(route.slice(route.indexOf('?') + 1).split('#')[0]);
  const query: Record<string, string> = {};
  for (const [key, item] of params.entries()) {
    if (NAVIGATION_QUERY_KEYS.has(key) && item) query[key] = item;
  }
  return query;
}

function instantiateLeafRoute(pattern: string, params: Record<string, string>): string {
  const values = { ...params };
  if (params['ref']) {
    const first = /:([A-Za-z][A-Za-z0-9]*)/.exec(pattern);
    if (first && !values[first[1]]) values[first[1]] = params['ref'];
  }
  return pattern.replace(LEAF_PARAM, (_, name: string) => {
    const value = values[name];
    if (!value) throw new Error(`Leaf route ${pattern} requires :${name}`);
    return encodeURIComponent(value);
  });
}

export function navigationSurfaceUrl(
  surfaceId: string,
  options: NavigationObjectUrlOptions = {},
): string {
  const surface = agentiumSurfaceById(surfaceId);
  if (!surface) throw new Error(`Unknown Agentium surface: ${surfaceId}`);
  const path = pathOnly(surface.route);
  const catalogQuery = queryFromRoute(surface.route);
  return appendNavigationQuery(path, {
    lens: lensQueryForPath(path, options.lens),
    tab: options.tab,
    facet: options.facet ?? catalogQuery['facet'] ?? null,
    scope: options.scope,
    capabilityId: options.capabilityId,
    systemId: options.systemId,
    runId: options.runId,
    skillRef: options.skillRef,
    doc: options.doc,
  });
}

export function navigationLeafUrl(
  leafId: string,
  params: Record<string, string> = {},
  options: NavigationObjectUrlOptions = {},
): string {
  const leaf = agentiumLeafById(leafId);
  if (!leaf) throw new Error(`Unknown Agentium leaf: ${leafId}`);
  const path = instantiateLeafRoute(leaf.route, params);
  return appendNavigationQuery(path, {
    lens: lensQueryForPath(path, options.lens),
    tab: options.tab,
    facet: options.facet,
    scope: options.scope,
    capabilityId: options.capabilityId,
    systemId: path.startsWith('/systems/') ? null : options.systemId,
    runId: options.runId,
    skillRef: options.skillRef,
    doc: options.doc,
  });
}

export interface NavLinkResolution {
  url: string;
  replaceUrl: boolean;
}

export function resolveNavLink(
  input: NavLinkInput,
  context: {
    lens: CockpitLens | null;
    ancestry: NavigationAncestry;
    currentUrl: string;
  },
): NavLinkResolution {
  const lens = 'lens' in input && input.lens !== undefined ? input.lens : context.lens;

  if ('type' in input) {
    return {
      url: navigationObjectUrl(input.type, input.ref, {
        ...context.ancestry,
        lens,
        facet: input.facet,
      }),
      replaceUrl: false,
    };
  }
  if ('surface' in input) {
    return {
      url: navigationSurfaceUrl(input.surface, {
        ...context.ancestry,
        lens,
        facet: input.facet,
      }),
      replaceUrl: false,
    };
  }
  if ('leaf' in input) {
    return {
      url: navigationLeafUrl(input.leaf, {
        ...(input.params ?? {}),
        ...(input.ref ? { ref: input.ref } : {}),
      }, {
        ...context.ancestry,
        lens,
        facet: input.facet,
      }),
      replaceUrl: false,
    };
  }

  const current = navigationRouteContext(context.currentUrl);
  return {
    url: appendNavigationQuery(current.path, {
      lens: lensQueryForPath(current.path, lens),
      facet: input.facet,
      scope: current.scope,
      capabilityId: input.capabilityId !== undefined
        ? input.capabilityId
        : current.selectedType === 'capability' ? null : current.capabilityId,
      systemId: current.selectedType === 'system' ? null : current.systemId,
      runId: current.selectedType === 'run' || current.selectedType === 'skill_invocation'
        ? null
        : current.runId,
      skillRef: current.selectedType === 'skill' ? null : current.skillRef,
      doc: current.query['doc'] ?? null,
    }),
    replaceUrl: true,
  };
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
      facet: options.facet,
      scope: options.scope,
      capabilityId: options.capabilityId,
      systemId: options.systemId,
    });
  }
  const path = `${agentiumSurfaceRoute(HIERARCHY_SURFACE_IDS[type])}/${encodeURIComponent(ref)}`;
  return appendNavigationQuery(path, {
    lens: lensQueryForPath(path, options.lens),
    tab: options.tab,
    facet: options.facet,
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
