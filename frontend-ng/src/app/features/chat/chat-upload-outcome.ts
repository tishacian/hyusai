export interface UploadedDocument {
  document_id?: string | null;
  filename?: string | null;
  status?: string | null;
  error?: string | null;
  reason?: string | null;
}

export interface UploadBatchOutcome {
  total: number;
  successful: number;
  failed: number;
  documents?: UploadedDocument[];
}

/** Only explicit per-file acknowledgements make a document available to chat. */
export function uploadOutcome(result: UploadBatchOutcome, filenames: readonly string[]) {
  const documents = result.documents ?? [];
  const acknowledged = new Set(documents.map((document) => document.filename).filter(Boolean));
  return {
    ready: documents.filter((document) => document.status === 'success' && !!document.filename),
    pending: documents.filter((document) => document.status === 'queued' || document.status === 'processing'),
    refused: [
      ...documents
        .filter((document) => document.status !== 'success' && document.status !== 'queued' && document.status !== 'processing')
        .map((document, index) => ({ filename: document.filename || filenames[index] || '—', reason: document.reason || document.error || '' })),
      ...filenames.filter((filename) => !acknowledged.has(filename))
        .filter((filename) => !documents.some((document, index) => !document.filename && filenames[index] === filename))
        .map((filename) => ({ filename, reason: '' })),
    ],
  };
}
