import type { SecretMeta } from '@app/shared/secrets/secrets.api';
export interface Field { key: string; kind: 'text' | 'column' | 'columns' | 'number' | 'boolean' | 'list' | 'select' | 'literal' | 'collection' | 'numbers' | 'secret' | 'literals' | 'options'; min?: number; max?: number; integer?: boolean; default?: unknown; options?: string[]; children?: Field[]; }
const column = (key = 'column'): Field => ({ key, kind: 'column' });
const columns = (key = 'columns'): Field => ({ key, kind: 'columns' });
const text = (key: string): Field => ({ key, kind: 'text' });
export const functions = ['count', 'sum', 'avg', 'min', 'max', 'stddev_samp', 'count_distinct'];
const select=(key:string,options:string[]):Field=>({key,kind:'select',options});
const numeric=(key:string):Field=>({key,kind:'number',integer:!['min','max'].includes(key)});
const boolean=(key:string):Field=>({key,kind:'boolean'});
const literal=(key:string):Field=>({key,kind:'literal'});
const collection=(key:string,children:Field[]):Field=>({key,kind:'collection',children});
export const PREP_FIELDS: Record<string, Field[]> = {

  move_columns:[columns(),select('position',['start','end','before','after']),column('anchor')],
  copy_column:[column(),text('output')],concat_columns:[columns(),text('separator'),text('output'),select('nulls',['skip','empty','propagate'])],
  normalize_column_names:[select('style',['snake','lower','ascii','papai']),select('dedupe',['fail','suffix'])],add_column:[text('output'),literal('value'),select('type',['text','double','integer','bigint','boolean','date','timestamp','timestamp_tz'])],
  parse_date:[column(),select('preset',['iso_date','iso_datetime','iso_datetime_tz','fr_date','fr_datetime','us_date','compact','rfc2822']),text('format'),select('to',['date','timestamp','timestamp_tz','auto']),text('output')],format_date:[column(),text('format'),text('output')],from_epoch:[column(),select('unit',['s','ms','us']),text('output')],
  parse_number:[column(),select('decimal_separator',['.',',']),text('thousands_separator'),text('output')],to_boolean:[columns(),{key:'true_values',kind:'list'},{key:'false_values',kind:'list'},boolean('case_sensitive')],
  drop_nulls:[columns(),select('how',['any','all']),boolean('nan_as_null')],fill_nulls:[columns(),select('method',['constant','mean','median','min','max','mode','ffill','bfill']),literal('value'),columns('order_by'),columns('partition_by')],
  filter_expression:[text('expression')],filter_range:[column(),numeric('min'),numeric('max'),boolean('min_inclusive'),boolean('max_inclusive')],
  filter_rows:[select('combine',['and','or']),collection('conditions',[column(),select('op',['eq','ne','lt','le','gt','ge','contains','starts_with','is_null','is_not_null']),literal('value')])],
  flag_rows:[text('output'),select('flag_when',['match','no_match']),collection('conditions',[column(),select('op',['eq','ne','lt','le','gt','ge','contains','starts_with','is_null','is_not_null']),literal('value')])],
  text_transform:[columns(),select('operation',['trim','ltrim','rtrim','lower','upper','title','remove_accents','collapse_spaces'])],
  replace_values:[columns(),select('match',['exact','substring','regex']),boolean('case_sensitive'),boolean('normalize_accents'),collection('pairs',[literal('from'),literal('to')])],
  map_values:[column(),text('output'),select('default',['keep','null','value']),literal('value'),collection('pairs',[literal('from'),literal('to')])],
  split_column:[column(),text('separator'),text('regex'),{key:'outputs',kind:'list'},select('remainder',['last','drop'])],extract_regex:[column(),text('pattern'),collection('outputs',[numeric('group'),text('name')])],
  count_occurrences:[column(),text('pattern'),select('match',['substring','regex']),boolean('case_sensitive'),text('output')],substring:[column(),numeric('start'),numeric('length'),text('output')],
  pad:[column(),numeric('length'),text('char'),select('side',['left','right']),text('output')],length:[column(),text('output')],negate_boolean:[columns()],
  bin_numeric:[column(),{key:'breaks',kind:'numbers'},{key:'labels',kind:'list'},text('output')],formula:[text('output'),text('expression')],
  conditional_column:[text('output'),collection('cases',[text('when'),literal('then')]),literal('else')],
  window:[select('function',['row_number','rank','dense_rank','percent_rank','ntile','lag','lead','first_value','last_value','cumulative_sum','cumulative_mean','cumulative_count','moving_mean','moving_sum']),column(),columns('partition_by'),columns('order_by'),numeric('offset'),numeric('size'),text('output')],
  mask:[columns(),numeric('keep_first'),numeric('keep_last'),text('char')],dedup:[columns(),select('keep',['first','last','none']),columns('order_by')],
  round:[columns(),numeric('decimals'),select('mode',['half_up','half_even','floor','ceil','truncate'])],math:[columns(),select('function',['abs','sqrt','ln','log10','exp','sign','ceil','floor'])],
  extract_date_parts:[column(),{key:'parts',kind:'options',options:['year','quarter','month','iso_week','day','iso_day_of_week','day_of_year','hour','minute','second','epoch_seconds']},text('naming')],date_diff:[column('start'),column('end'),select('unit',['second','minute','hour','day','week','month','quarter','year']),text('output')],
  date_add:[column(),numeric('amount'),select('unit',['second','minute','hour','day','week','month','quarter','year']),text('output')],truncate_date:[column(),select('unit',['second','minute','hour','day','week','month','quarter','year']),text('output')],convert_timezone:[column(),text('from'),text('to'),text('output')],scale:[columns(),select('method',['zscore','minmax','robust']),text('output_suffix')],
  select_columns: [columns()], drop_columns: [columns()], rename_columns: [],
  prepare: [], join: [{ key: 'how', kind: 'select', options: ['left', 'inner', 'full', 'right'] }], union: [{ key: 'distinct', kind: 'boolean' }],
  aggregate: [columns('group_by')], pivot: [columns('group_by'), column(), { key: 'values', kind: 'literals' }, column('value_column'), { key: 'function', kind: 'select', options: functions.slice(0, 5) }],
  unpivot: [columns(), text('name_column'), text('value_column')], split: [columns('keys'), columns('stratify')], sample: [columns('keys'), columns('stratify'), { key: 'rows', kind: 'number' }],
  select: [columns()], drop: [columns()], drop_null: [columns()], deduplicate: [columns()],
  sort: [columns(), { key: 'descending', kind: 'boolean' }], filter: [text('expression')], derive: [text('name'), text('expression')],
  cast: [column(), { key: 'type', kind: 'select', options: ['VARCHAR', 'DOUBLE', 'BIGINT', 'INTEGER', 'BOOLEAN', 'DATE', 'TIMESTAMP', 'timestamp_tz', 'DECIMAL'] }],
  fill_null: [column(), {key: 'value', kind: 'literal'}], trim: [column()], upper: [column()], lower: [column()],
  replace: [column(), text('old'), text('new')], date_format: [column(), text('format')], hash: [columns(), text('output'),{key:'salt_secret_ref',kind:'secret'}], rename: [],
};

// Values displayed by untouched controls must match compiler defaults.
const DEFAULTS: Record<string, Record<string, unknown>> = {
  drop_nulls: {how: 'any', nan_as_null: true},
  filter_range: {min_inclusive: true, max_inclusive: true},
  replace_values: {match: 'exact', case_sensitive: true, normalize_accents: false},
  count_occurrences: {match: 'substring', case_sensitive: true},
  to_boolean: {case_sensitive: false, true_values: ['true','t','yes','y','1','oui'], false_values: ['false','f','no','n','0','non']},
  concat_columns: {nulls: 'skip', separator: ''},
  normalize_column_names: {dedupe: 'fail'}, parse_date: {to: 'auto'},
  from_epoch: {unit: 's'}, parse_number: {decimal_separator: '.'},
  filter_rows: {combine: 'and'}, flag_rows: {combine: 'and', flag_when: 'match'},
  map_values: {default: 'keep'}, split_column: {remainder: 'last'},
  substring: {start: 1}, pad: {char: ' ', side: 'left'},
  mask: {keep_first: 0, keep_last: 0, char: '*'},
  dedup: {keep: 'first'}, round: {decimals: 0, mode: 'half_up'},
  extract_date_parts: {naming: '{column}_{part}'},
  union: {distinct: false}, sort: {descending: false},
};
const LIMITS: Record<string, Record<string, [number, number]>> = {
  substring: {start: [1, Number.MAX_SAFE_INTEGER], length: [0, Number.MAX_SAFE_INTEGER]},
  pad: {length: [0, 10000]}, mask: {keep_first: [0,10000], keep_last: [0,10000]},
  round: {decimals: [-12,12]}, date_add: {amount: [-1000000,1000000]},
  window: {offset: [1,10000], size: [1,100000]}, extract_regex: {group: [0,1000]},
};
export function prepFieldDefault(kind: string, key: string): unknown { return DEFAULTS[kind]?.[key]; }
export function prepStepDefaults(kind: string): Record<string, unknown> { return structuredClone(DEFAULTS[kind] ?? {}); }
export function prepFields(kind: string): Field[] { return (PREP_FIELDS[kind] ?? []).map(field => ({...field, min: LIMITS[kind]?.[field.key]?.[0], max: LIMITS[kind]?.[field.key]?.[1]})); }
export function prepNumber(text: string): number | undefined { const n = Number(text); return text.trim() && Number.isFinite(n) ? n : undefined; }
export function prepParamChange(params: Record<string, unknown>, key: string, value: unknown): Record<string, unknown> {
  const next = {...params}; if (value === undefined) delete next[key]; else next[key] = value; return next;
}

export function validatePrepParams(kind: string, params: Record<string, unknown>): boolean {
  const fields = prepFields(kind);
  for (const field of fields) {
    const value = params[field.key]; if (value === undefined) continue;
    if (field.kind === 'boolean' && typeof value !== 'boolean') return false;
    if (field.kind === 'select' && !field.options?.includes(String(value))) return false;
    if (field.kind === 'number' && (typeof value !== 'number' || !Number.isFinite(value) || field.integer !== false && !Number.isInteger(value) || field.min != null && value < field.min || field.max != null && value > field.max)) return false;
    if (['columns','list','options','numbers','literals','collection'].includes(field.kind) && !Array.isArray(value)) return false;
  }
  if (kind === 'window' && params['function'] === 'ntile' && typeof params['size'] === 'number' && params['size'] > 10000) return false;
  if (kind === 'sample' && typeof params['rows'] === 'number' && params['rows'] < 0) return false;
  if (kind === 'split_column' && Array.isArray(params['outputs']) && params['outputs'].length > 50) return false;
  return true;
}

export function prepStepParamChange(kind: string, params: Record<string, unknown>, key: string, value: unknown): Record<string, unknown> {
  const next = prepParamChange(params,key,value);
  if (kind === 'replace_values' && key === 'match' && value !== 'exact') next['normalize_accents'] = false;
  if (kind === 'parse_date' && key === 'preset' && value) delete next['format'];
  if (kind === 'parse_date' && key === 'format' && value) delete next['preset'];
  if (kind === 'split_column' && key === 'separator' && value) delete next['regex'];
  return next;
}

export function hashSaltOptions(secrets: SecretMeta[]): Array<{name:string; ref:string; version:number}> {
  return secrets.filter(secret => secret.scope === 'workspace' && secret.kind === 'generic' && secret.metadata?.['purpose'] === 'dataops_hash_salt' && !secret.disabled_at && secret.value_set)
    .flatMap(secret => secret.versions.filter(version => !version.destroyed_at).map(version => ({name:secret.name,ref:secret.ref.split('#')[0]+'#'+version.version,version:version.version})));
}
