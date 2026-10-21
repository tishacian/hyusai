export type DepositReceiptState = 'received' | 'rejected' | 'promoted' | 'unknown' | 'failed';
export interface DepositReceipt { filename: string; state: DepositReceiptState; reason: string | null; }

export function depositReceipt(filename: string, response: unknown): DepositReceipt {
  const file = response && typeof response === 'object' ? (response as { file?: unknown }).file : null;
  if (!file || typeof file !== 'object') return { filename, state: 'unknown', reason: null };
  const record = file as { status?: unknown; rejection_reason?: unknown };
  const state = record.status === 'received' || record.status === 'rejected' || record.status === 'promoted' ? record.status : 'unknown';
  return { filename, state, reason: state === 'rejected' && typeof record.rejection_reason === 'string' ? record.rejection_reason : null };
}

export function failedDepositReceipt(filename: string, error: unknown): DepositReceipt {
  const status = error && typeof error === 'object' ? Number((error as { status?: unknown }).status) : 0;
  // A lost response can hide a successful upload. Never offer to replay it blindly.
  const unknown = !status || status === 408 || status === 502 || status === 504;
  const state = unknown ? 'unknown' : status === 413 || status === 415 || status === 422 ? 'rejected' : 'failed';
  return { filename, state, reason: null };
}
