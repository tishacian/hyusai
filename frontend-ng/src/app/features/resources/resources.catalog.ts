/**
 * Canonical catalog of connectors and packaged apps the platform exposes.
 *
 * Mental model — "apps" ≠ "skills":
 *   - `/apps`   = packaged **integrations** (connectors, vertical templates).
 *                 Catalog-level toggles, governed under the `Govern` verb.
 *   - `/skills` = atomic, typed, versioned **operations** (the registry
 *                 orchestrated by Systems). Lives under the `Build` verb.
 *
 * Only `sharepoint` has a real backend today; every other app is a vitrine
 * card — matches the legacy HTML frontend behaviour in a typed, reusable
 * shape.
 *
 * Both lists are pure data so they can be imported by:
 *   - the Resources page (Models + Connectors + Apps overview tabs),
 *   - the dedicated `/apps` route with persisted toggles,
 *   - the System Builder wizard ("Skills" step, which resolves references
 *     against `/skills` — not this file).
 */

export type ConnectorStatus = 'active' | 'available' | 'coming-soon';
export type ConnectorCategory = 'microsoft' | 'channels' | 'data-storage';

export interface ConnectorField {
  key: string;
  label: string;
  type: 'text' | 'url' | 'password' | 'email' | 'number';
  placeholder?: string;
  required?: boolean;
}

export interface ConnectorDef {
  id: string;
  category: ConnectorCategory;
  icon: string;
  name: string;
  description: string;
  version: string;
  status: ConnectorStatus;
  /** REST prefix under `/api/v1/` when a real backend exists. */
  backendPrefix?: string;
  fields: ConnectorField[];
}

export const CONNECTOR_CATEGORIES: {
  id: ConnectorCategory;
  label: string;
  icon: string;
}[] = [
  { id: 'microsoft', label: 'Microsoft 365', icon: 'cloud' },
  { id: 'channels', label: 'Communication channels', icon: 'send' },
  { id: 'data-storage', label: 'Data & storage', icon: 'database' },
];

export const CONNECTORS: ConnectorDef[] = [
  // Microsoft 365
  {
    id: 'dynamics365',
    category: 'microsoft',
    icon: 'cloud',
    name: 'Dynamics 365',
    description: 'ERP / CRM data, vendor records, purchase orders.',
    version: 'v9.2',
    status: 'available',
    fields: [
      { key: 'tenant_url', label: 'Tenant URL', type: 'url', placeholder: 'https://org.crm4.dynamics.com', required: true },
      { key: 'client_id', label: 'Client ID', type: 'text', placeholder: 'app-client-id', required: true },
      { key: 'client_secret', label: 'Client secret', type: 'password', placeholder: '••••••••' },
      { key: 'default_entity', label: 'Default entity', type: 'text', placeholder: 'accounts' },
    ],
  },
  {
    id: 'teams',
    category: 'microsoft',
    icon: 'message-circle',
    name: 'Microsoft Teams',
    description: 'Notifications and agent conversations via Teams channels.',
    version: 'Graph API v1.0',
    status: 'available',
    fields: [
      { key: 'webhook_url', label: 'Incoming webhook URL', type: 'url', placeholder: 'https://outlook.office.com/webhook/…' },
      { key: 'tenant_id', label: 'Tenant ID', type: 'text', placeholder: 'contoso.onmicrosoft.com' },
      { key: 'bot_id', label: 'Bot app ID', type: 'text' },
    ],
  },
  {
    id: 'sharepoint',
    category: 'microsoft',
    icon: 'folder',
    name: 'Microsoft SharePoint',
    description: 'Document libraries, policy repositories, delegated OTP auth.',
    version: 'REST API v2',
    status: 'active',
    backendPrefix: 'sharepoint',
    fields: [
      { key: 'site_url', label: 'Site URL', type: 'url', placeholder: 'https://tenant.sharepoint.com/sites/policies', required: true },
      { key: 'client_id', label: 'Client ID', type: 'text', required: true },
      { key: 'client_secret', label: 'Client secret', type: 'password' },
      { key: 'scope', label: 'OAuth scope', type: 'text', placeholder: 'Sites.Read.All' },
    ],
  },
  {
    id: 'outlook',
    category: 'microsoft',
    icon: 'mail',
    name: 'Outlook / Exchange',
    description: 'Inbound email triggers, calendar events, task sync.',
    version: 'EWS / Graph',
    status: 'available',
    fields: [
      { key: 'mailbox', label: 'Monitored mailbox', type: 'email', placeholder: 'agent@company.com', required: true },
      { key: 'tenant_id', label: 'Tenant ID', type: 'text' },
      { key: 'shared', label: 'Shared mailbox alias', type: 'email' },
    ],
  },
  {
    id: 'institutional_calendar',
    category: 'microsoft',
    icon: 'calendar',
    name: 'Institutional agenda',
    description: 'Shared workspace agenda, readable and editable by authorized assistants.',
    version: 'Internal shared v1',
    status: 'active',
    backendPrefix: 'calendar',
    fields: [],
  },

  // Communication channels
  {
    id: 'telegram',
    category: 'channels',
    icon: 'send',
    name: 'Telegram Bot',
    description: 'Chat interaction via Telegram bot API.',
    version: 'Bot API 7.x',
    status: 'available',
    fields: [
      { key: 'bot_token', label: 'Bot token', type: 'password', required: true },
      { key: 'chat_id', label: 'Chat / channel ID', type: 'text', placeholder: '-1001234567890' },
      { key: 'webhook_url', label: 'Webhook URL', type: 'url' },
    ],
  },
  {
    id: 'whatsapp',
    category: 'channels',
    icon: 'message-square',
    name: 'WhatsApp Business',
    description: 'System access via WhatsApp Cloud API.',
    version: 'Cloud API v18',
    status: 'coming-soon',
    fields: [
      { key: 'phone_number_id', label: 'Phone number ID', type: 'text' },
      { key: 'access_token', label: 'Access token', type: 'password' },
      { key: 'business_id', label: 'Business ID', type: 'text' },
    ],
  },
  {
    id: 'smtp',
    category: 'channels',
    icon: 'mail',
    name: 'SMTP / Email',
    description: 'Inbound & outbound email agent triggers.',
    version: 'SMTP / IMAP',
    status: 'available',
    fields: [
      { key: 'host', label: 'SMTP host', type: 'text', placeholder: 'smtp.gmail.com', required: true },
      { key: 'port', label: 'Port', type: 'number', placeholder: '587' },
      { key: 'username', label: 'Username', type: 'text' },
      { key: 'password', label: 'Password', type: 'password' },
    ],
  },
  {
    id: 'rest_api',
    category: 'channels',
    icon: 'braces',
    name: 'REST API',
    description: 'Custom integrations via documented REST endpoints.',
    version: 'OpenAPI 3.1',
    status: 'active',
    fields: [
      { key: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
      { key: 'auth_header', label: 'Auth header', type: 'text', placeholder: 'Authorization' },
      { key: 'api_key', label: 'API key', type: 'password' },
    ],
  },
  {
    id: 'mqtt',
    category: 'channels',
    icon: 'network',
    name: 'MQTT',
    description: 'IoT and real-time event-driven messaging.',
    version: 'MQTT v5.0',
    status: 'available',
    fields: [
      { key: 'broker_url', label: 'Broker URL', type: 'text', placeholder: 'tls://broker.example.com:8883' },
      { key: 'topic', label: 'Topic pattern', type: 'text', placeholder: 'factory/+/telemetry' },
      { key: 'client_id', label: 'Client ID', type: 'text' },
      { key: 'username', label: 'Username', type: 'text' },
      { key: 'password', label: 'Password', type: 'password' },
    ],
  },
  {
    id: 'visual_streams',
    category: 'channels',
    icon: 'camera',
    name: 'Institutional visual streams',
    description: 'Snapshot capture from public or authorized streams, observations and Knowledge sync.',
    version: 'Snapshot v1',
    status: 'active',
    backendPrefix: 'visual-intelligence',
    fields: [],
  },

  // Data & storage
  {
    id: 'postgresql',
    category: 'data-storage',
    icon: 'database',
    name: 'PostgreSQL',
    description: 'Structured data queries and analytics.',
    version: 'v16',
    status: 'active',
    fields: [
      { key: 'host', label: 'Host', type: 'text', placeholder: 'localhost', required: true },
      { key: 'port', label: 'Port', type: 'number', placeholder: '5432' },
      { key: 'database', label: 'Database', type: 'text', required: true },
      { key: 'username', label: 'Username', type: 'text' },
      { key: 'password', label: 'Password', type: 'password' },
    ],
  },
  {
    id: 's3',
    category: 'data-storage',
    icon: 'cloud-upload',
    name: 'AWS S3',
    description: 'Cloud object storage for documents, embeddings, artifacts.',
    version: 'SDK v3',
    status: 'available',
    fields: [
      { key: 'bucket', label: 'Bucket', type: 'text', placeholder: 'company-data', required: true },
      { key: 'region', label: 'Region', type: 'text', placeholder: 'eu-west-1' },
      { key: 'access_key_id', label: 'Access key ID', type: 'text' },
      { key: 'secret_access_key', label: 'Secret access key', type: 'password' },
    ],
  },
  {
    id: 'sftp',
    category: 'data-storage',
    icon: 'inbox',
    name: 'SFTP / Secure Deposit',
    description: 'External upload links with password access and staged review before Knowledge ingestion.',
    version: 'Deposit v1',
    status: 'active',
    backendPrefix: 'sftp',
    fields: [],
  },
  {
    id: 'elasticsearch',
    category: 'data-storage',
    icon: 'server',
    name: 'Elasticsearch',
    description: 'Full-text search and log analytics.',
    version: 'v8.x',
    status: 'coming-soon',
    fields: [
      { key: 'cluster_url', label: 'Cluster URL', type: 'url', placeholder: 'https://es.company.com:9200' },
      { key: 'api_key', label: 'API key', type: 'password' },
    ],
  },
];

// ─── Apps / Skills / Tools ───────────────────────────────────────────────────

export type AppStatus = 'ready' | 'beta';

export interface AppDef {
  id: string;
  name: string;
  description: string;
  icon: string;
  status: AppStatus;
}

export const APPS: AppDef[] = [
  { id: 'web_search',      name: 'Web Search',        description: 'Search the internet for real-time information and news.', icon: 'globe',        status: 'beta'  },
  { id: 'code_interpreter', name: 'Code Interpreter', description: 'Execute Python and analyze data programmatically.',       icon: 'terminal',     status: 'beta'  },
  { id: 'sql_query',       name: 'SQL Query',         description: 'Query structured databases and export results.',          icon: 'database',     status: 'ready' },
  { id: 'api_connector',   name: 'API Connector',     description: 'Call external REST APIs with custom authentication.',     icon: 'plug',         status: 'ready' },
  { id: 'email_sender',    name: 'Email Sender',      description: 'Draft and send emails from agent workflows.',             icon: 'mail',         status: 'ready' },
  { id: 'file_generator',  name: 'File Generator',    description: 'Export agent output as PDF, Excel, or CSV.',              icon: 'file-text',    status: 'beta'  },
  { id: 'calendar_access', name: 'Calendar Access',   description: 'Read and write calendar events and schedules.',           icon: 'calendar',     status: 'beta'  },
  { id: 'memory',          name: 'Persistent Memory', description: 'Store and retrieve context across sessions.',             icon: 'brain',        status: 'ready' },
];

// ─── Local persistence helpers ───────────────────────────────────────────────

const CONNECTORS_LS_KEY = 'agentium:connectors:v1';
const APPS_LS_KEY = 'agentium:apps:v1';

export function readConnectorConfig(id: string): Record<string, string> {
  try {
    const raw = localStorage.getItem(CONNECTORS_LS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed?.[id] ?? {};
  } catch {
    return {};
  }
}

export function writeConnectorConfig(id: string, values: Record<string, string>): void {
  try {
    const raw = localStorage.getItem(CONNECTORS_LS_KEY);
    const all = raw ? JSON.parse(raw) : {};
    all[id] = values;
    localStorage.setItem(CONNECTORS_LS_KEY, JSON.stringify(all));
  } catch {
    /* quota — ignore */
  }
}

export function hasConnectorConfig(id: string): boolean {
  const cfg = readConnectorConfig(id);
  return Object.values(cfg).some((v) => typeof v === 'string' && v.trim().length > 0);
}

export function readAppToggles(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(APPS_LS_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export function writeAppToggle(id: string, enabled: boolean): void {
  try {
    const all = readAppToggles();
    all[id] = enabled;
    localStorage.setItem(APPS_LS_KEY, JSON.stringify(all));
  } catch {
    /* ignore */
  }
}
