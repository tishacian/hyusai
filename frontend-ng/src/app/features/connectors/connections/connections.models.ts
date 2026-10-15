export interface ConnectionParameter {
  key: string;
  type: 'string' | 'integer' | 'boolean' | 'enum' | 'host' | 'secret' | 'secret_file' | 'json';
  required: boolean;
  default?: unknown;
  choices: string[];
  min?: number | null;
  max?: number | null;
  pattern?: string | null;
  advanced: boolean;
  when: Record<string, unknown[]>;
}
export interface ConnectionProfile {
  key: string; version: number; family: string; parameters: ConnectionParameter[];
  /** i18n key of the display name, shared with the connector catalogue. */
  label_key?: string;
  capabilities: Record<string, boolean | string>;
  certification: 'unverified' | 'third_party'; driver_status: string;
}
export interface ConnectionRow {
  id: string; name: string; profile_key: string; profile_version: number; revision: number;
  values: Record<string, unknown>; secret_refs: Record<string, string>;
  access: 'read' | 'read_write'; allowed_schemas: string[]; allowed_tables: string[];
  certification: string;
}
export interface ConnectionRun {
  id: string; connection_id: string; operation: string; status: string; error_code?: string | null;
  output?: Record<string, any> | null; metrics?: Record<string, unknown>; cancel_requested?: boolean;
}
export interface ConnectionGrant {
  id: string; owner_user_id: string; scopes: string[]; expires_at: string | null; revoked_at: string | null;
}
export interface ToolContract { id: string; write: boolean; input_schema: { properties?: Record<string, any>; required?: string[] }; }
export const TERMINAL_CONNECTION_RUNS = new Set(['succeeded', 'failed', 'cancelled', 'timed_out', 'lost']);
export function parameterEnabled(parameter: ConnectionParameter, values: Record<string, unknown>): boolean {
  return Object.entries(parameter.when ?? {}).every(([key, choices]) => choices.includes(values[key]));
}
export function connectionPayload(profile: ConnectionProfile, name: string, fields: Record<string, unknown>, refs: Record<string, string>, access: 'read' | 'read_write', schemas: string[], tables: string[]) {
  const values: Record<string, unknown> = {}, secret_refs: Record<string, string> = {};
  if (!name.trim()) throw new Error('name');
  for (const parameter of profile.parameters) {
    if (parameter.type === 'secret' || parameter.type === 'secret_file') {
      const ref = refs[parameter.key];
      if (ref) {
        if (!/^secret:\/\/workspace\/[a-z0-9][a-z0-9._-]*(#[1-9][0-9]*)?$/.test(ref)) throw new Error(parameter.key);
        secret_refs[parameter.key] = ref;
      } else if (parameter.required && parameterEnabled(parameter, fields)) throw new Error(parameter.key);
      continue;
    }
    let value = fields[parameter.key];
    if (value === undefined || value === null || value === '') {
      if (parameter.required && parameterEnabled(parameter, fields)) throw new Error(parameter.key);
      continue;
    }
    if (parameter.type === 'json' && typeof value === 'string') value = JSON.parse(value);
    if (parameter.type === 'integer') {
      if (typeof value !== 'string' && typeof value !== 'number') throw new Error(parameter.key);
      value = Number(value);
      if (!Number.isInteger(value) || (parameter.min != null && Number(value) < parameter.min) || (parameter.max != null && Number(value) > parameter.max)) throw new Error(parameter.key);
    }
    if (parameter.type === 'boolean' && typeof value !== 'boolean') throw new Error(parameter.key);
    if (parameter.type === 'enum' && !parameter.choices.includes(String(value))) throw new Error(parameter.key);
    if (parameter.pattern && !new RegExp(`^(?:${parameter.pattern})$`).test(String(value))) throw new Error(parameter.key);
    values[parameter.key] = value;
  }
  return { name: name.trim(), profile_key: profile.key, values, secret_refs, access, allowed_schemas: schemas, allowed_tables: tables };
}
