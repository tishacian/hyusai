export const API_BASE = '/api/v1';

export async function fetchJSON(path, opts = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
        headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
        ...opts,
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
    return res.json();
}

export async function listAgents() {
    return fetchJSON('/agents');
}

export async function getAuditSummary() {
    return fetchJSON('/audit/summary');
}

export async function createAuditEvent(event) {
    return fetchJSON('/audit', {
        method: 'POST',
        body: JSON.stringify(event),
    });
}

export async function listAuditLogs(limit = 20) {
    return fetchJSON(`/audit?limit=${limit}`);
}

export async function getDocumentStats() {
    return fetchJSON('/documents/stats');
}

export async function listDocuments() {
    return fetchJSON('/documents/list');
}

export async function previewDocument(documentId) {
    return fetchJSON(`/documents/preview/${documentId}`);
}

export async function clearAllDocuments() {
    const res = await fetch(`${API_BASE}/documents/clear`, { method: 'DELETE' });
    if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(`${res.status}: ${body}`);
    }
    return res.json();
}

export async function deleteDocument(documentId) {
    const res = await fetch(`${API_BASE}/documents/${documentId}`, { method: 'DELETE' });
    if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(`${res.status}: ${body}`);
    }
    return res.json();
}

export async function uploadDocument(file) {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/documents/upload`, {
        method: 'POST',
        body: formData,
    });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    return res.json();
}

export async function transcribeAudio(blob) {
    const formData = new FormData();
    formData.append('file', blob, 'recording.webm');
    const res = await fetch(`${API_BASE}/voice/transcribe`, {
        method: 'POST',
        body: formData,
    });
    if (!res.ok) throw new Error(`Transcription failed: ${res.status}`);
    return res.json();
}

export async function synthesizeSpeech(text, voice = 'nova') {
    const res = await fetch(`${API_BASE}/voice/synthesize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice }),
    });
    if (!res.ok) throw new Error(`Speech synthesis failed: ${res.status}`);
    return res.blob();
}

/**
 * Stream a chat completion via SSE.
 * @param {string} query
 * @param {object} opts
 * @param {function} onChunk - called with each parsed SSE event
 * @param {function} onDone - called when stream completes
 * @param {function} onError - called on error
 */
export function streamChat(query, opts, onChunk, onDone, onError) {
    const body = {
        query,
        stream: true,
        temperature: opts.temperature ?? 0.3,
        system_prompt: opts.system_prompt || null,
        agent_preferences: {
            preferred_agents: [],
            model_preferences: {
                model: opts.model || 'gpt-5',
                provider: opts.provider || 'openai',
            },
        },
    };

    fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    }).then(response => {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        function read() {
            reader.read().then(({ done, value }) => {
                if (done) {
                    onDone && onDone();
                    return;
                }
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // keep incomplete line

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6).trim();
                        if (data === '[DONE]') {
                            onDone && onDone();
                            return;
                        }
                        try {
                            const parsed = JSON.parse(data);
                            onChunk(parsed);
                        } catch (e) {
                            // ignore malformed JSON
                        }
                    }
                }
                read();
            }).catch(err => {
                onError && onError(err);
            });
        }
        read();
    }).catch(err => {
        onError && onError(err);
    });
}
