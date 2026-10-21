/** Capabilities of the shipped connector APIs, not connection health or permission. */
export const CONNECTOR_ACTIONS = ['configure', 'test', 'import', 'schedule', 'write', 'revoke'] as const;
export type ConnectorAction = typeof CONNECTOR_ACTIONS[number];
export type ConnectorCapabilities = Readonly<Record<ConnectorAction, boolean>>;

const capabilities = (...supported: ConnectorAction[]): ConnectorCapabilities =>
  Object.fromEntries(CONNECTOR_ACTIONS.map(action => [action, supported.includes(action)])) as Record<ConnectorAction, boolean>;

const SHIPPED: Readonly<Record<string, ConnectorCapabilities>> = {
  postgresql: capabilities('configure', 'test', 'import', 'revoke'),
  hana: capabilities('configure', 'test'),
  sap_hana: capabilities('configure', 'test'),
  huggingface: capabilities('configure', 'test', 'import', 'revoke'),
  sharepoint: capabilities('configure', 'test', 'import', 'revoke'),
  mcp: capabilities('configure', 'test', 'write', 'revoke'),
  rpa_bridge: capabilities('configure', 'test', 'write', 'revoke'),
  sftp: capabilities('configure', 'import', 'revoke'),
  // The S3 drawer configures credentials; the Connections API owns these operations.
  s3: capabilities('configure', 'test', 'import', 'schedule', 'write', 'revoke'),
};

export function connectorCapabilities(id: string, generic?: { available: boolean; testable: boolean }): ConnectorCapabilities {
  if (SHIPPED[id]) return SHIPPED[id];
  return generic?.available
    ? capabilities('configure', ...(generic.testable ? ['test' as const] : []), 'revoke')
    : capabilities();
}

export type ConnectionCheckState = 'passed' | 'failed' | 'unknown' | 'not-tested';
export interface ConnectionChecks {
  configuration: ConnectionCheckState;
  authentication: ConnectionCheckState;
  resource: ConnectionCheckState;
  reason: 'not_configured' | 'auth_failed' | 'access_denied' | 'unreachable' | 'unsupported' | 'unknown' | 'connected';
}

/** Empty/ambiguous responses never prove successful authentication or resource access. */
export function connectionChecks(result: unknown, configured: boolean | null): ConnectionChecks {
  const row = result && typeof result === 'object' ? result as Record<string, unknown> : {};
  const code = String(row['status'] ?? row['code'] ?? '');
  const checks: ConnectionChecks = {
    configuration: configured === true ? 'passed' : configured === false ? 'failed' : 'unknown',
    authentication: 'not-tested', resource: 'not-tested', reason: 'unknown',
  };
  if (!result) return checks;
  if (row['ok'] === true || code === 'connected') {
    return { configuration: 'passed', authentication: 'passed', resource: 'passed', reason: 'connected' };
  }
  if (code === 'not_configured' || code === 'mcp_unconfigured') {
    checks.configuration = 'failed'; checks.reason = 'not_configured';
  } else if (code === 'auth_failed') {
    checks.authentication = 'failed'; checks.reason = 'auth_failed';
  } else if (code === 'access_denied') {
    checks.authentication = 'unknown'; checks.resource = 'failed'; checks.reason = 'access_denied';
  } else {
    checks.authentication = 'unknown'; checks.resource = 'unknown';
    checks.reason = code === 'unreachable' || code === 'unsupported' ? code : 'unknown';
  }
  return checks;
}
