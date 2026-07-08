import type { CkGlyphName } from '@app/shared/cockpit';
import type { WorkspaceMode } from '@app/core/workspace.service';

export type CockpitLens = 'hypervisor' | 'build' | 'operate' | 'steer' | 'govern';

export type AgentiumObjectType =
  | 'Workspace'
  | 'Capability'
  | 'System'
  | 'Skill'
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
    lens: 'hypervisor',
    object: 'Workbench',
    scope: 'workspace',
    apiPrefix: '/api/v1/mission-room',
    status: 'canonical',
    audience: 'workspace-user',
    description: 'Executive government cockpit for briefing, projects, open intelligence, map and advisory actions.',
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
  route: string;
  matches?: string[];
  scopeType: CockpitScopeType;
}

export interface CockpitVerb {
  key: CockpitLens;
  label: string;
  hint: string;
  glyph: CkGlyphName;
  primaryRoute: string;
  matches: string[];
  sections?: CockpitSection[];
  hiddenInModes?: WorkspaceMode[];
}

export const COCKPIT_VERBS: CockpitVerb[] = [
  {
    key: 'hypervisor',
    label: 'Hypervisor',
    hint: 'Decide · balance sheet, outcomes, what-if',
    glyph: 'ledger',
    primaryRoute: '/hypervisor',
    matches: ['/hypervisor'],
    hiddenInModes: ['builder'],
  },
  {
    key: 'build',
    label: 'Build',
    hint: 'Create Systems, Capabilities, Skills, Knowledge & Flows',
    glyph: 'cube',
    primaryRoute: '/systems',
    matches: ['/systems', '/capabilities', '/skills', '/knowledge', '/orchestration'],
    sections: [
      { key: 'systems', label: 'Systems', glyph: 'cube', route: '/systems', scopeType: 'system' },
      { key: 'capabilities', label: 'Capabilities', glyph: 'focus', route: '/capabilities', scopeType: 'capability' },
      { key: 'skills', label: 'Skills', glyph: 'bolt', route: '/skills', scopeType: 'skill' },
      { key: 'knowledge', label: 'Knowledge', glyph: 'layers', route: '/knowledge', scopeType: 'knowledge' },
      { key: 'flows', label: 'Flow builder', glyph: 'flow', route: '/orchestration', scopeType: 'flow' },
    ],
  },
  {
    key: 'operate',
    label: 'Operate',
    hint: 'Run Systems · runtime, runs, missions',
    glyph: 'telemetry',
    primaryRoute: '/runs',
    matches: ['/runs', '/observability', '/intelligence', '/tasks', '/chat'],
    sections: [
      { key: 'runs', label: 'Runs', glyph: 'ledger', route: '/runs', scopeType: 'run' },
      { key: 'observability', label: 'Observability', glyph: 'telemetry', route: '/observability', scopeType: 'system' },
      { key: 'intelligence', label: 'Intelligence', glyph: 'pulse', route: '/intelligence', scopeType: 'system' },
      { key: 'missions', label: 'Missions', glyph: 'play', route: '/tasks', scopeType: 'run' },
    ],
  },
  {
    key: 'steer',
    label: 'Steer',
    hint: 'Optimize Outcomes · levers, policies, simulations',
    glyph: 'sliders',
    primaryRoute: '/steering',
    matches: ['/steering'],
    sections: [
      { key: 'levers', label: 'Control plane', glyph: 'sliders', route: '/steering', scopeType: 'system' },
      { key: 'contexts', label: 'Contexts', glyph: 'crosshair', route: '/steering/contexts', scopeType: 'context' },
      { key: 'review', label: 'Review queue', glyph: 'warn', route: '/steering/review-queue', scopeType: 'system' },
    ],
    hiddenInModes: ['builder'],
  },
  {
    key: 'govern',
    label: 'Govern',
    hint: 'Control · audit, apps, resources, presets',
    glyph: 'shield',
    primaryRoute: '/governance',
    matches: ['/governance', '/apps', '/resources', '/connectors', '/presets', '/settings', '/workspace', '/account'],
    sections: [
      { key: 'audit', label: 'Governance', glyph: 'shield', route: '/governance', scopeType: 'system' },
      { key: 'workspace', label: 'Workspace settings', glyph: 'sliders', route: '/workspace', scopeType: 'system' },
      { key: 'apps', label: 'Apps', glyph: 'bolt', route: '/apps', scopeType: 'app' },
      { key: 'resources', label: 'Resources', glyph: 'orbit', route: '/resources', scopeType: 'system' },
      { key: 'connectors', label: 'Connectors', glyph: 'layers', route: '/connectors', matches: ['/connectors'], scopeType: 'connector' },
      { key: 'presets', label: 'Presets', glyph: 'sliders', route: '/presets', scopeType: 'preset' },
    ],
  },
];

export const LENS_MATCHES: Record<CockpitLens, string[]> = COCKPIT_VERBS.reduce(
  (acc, verb) => ({ ...acc, [verb.key]: verb.matches }),
  {} as Record<CockpitLens, string[]>,
);

export function matchCockpitVerb(path: string): CockpitVerb | null {
  return COCKPIT_VERBS.find((v) => v.matches.some((m) => path === m || path.startsWith(m + '/'))) ?? null;
}
