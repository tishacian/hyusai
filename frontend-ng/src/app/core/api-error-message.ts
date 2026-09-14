type ApiErrorEnvelope = {
  error?: unknown;
  message?: unknown;
};

function readableDetail(value: unknown): string | null {
  if (typeof value === 'string') return value.trim() || null;

  if (Array.isArray(value)) {
    const messages = value
      .map((item) => readableDetail(item))
      .filter((item): item is string => Boolean(item));
    return messages.length ? messages.join('; ') : null;
  }

  if (!value || typeof value !== 'object') return null;

  const detail = value as Record<string, unknown>;
  for (const key of ['message', 'msg', 'detail']) {
    const message = readableDetail(detail[key]);
    if (message) return message.replace(/^Value error,\s*/i, '');
  }
  return null;
}

/** Render API failures without leaking JavaScript's `[object Object]` coercion. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  const envelope = (error && typeof error === 'object' ? error : {}) as ApiErrorEnvelope;
  const body = envelope.error;
  const detail =
    body && typeof body === 'object'
      ? (body as Record<string, unknown>)['detail'] ?? body
      : body;
  return readableDetail(detail) ?? readableDetail(envelope.message) ?? fallback;
}
