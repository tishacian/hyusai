import { randomUUID } from 'node:crypto';

// Optional realtime STT internals to the container console (docker logs).
// Gated off by default; enable with LIVEKIT_AGENT_DEBUG_RTSTT=1.
const DEBUG_RTSTT = String(process.env.LIVEKIT_AGENT_DEBUG_RTSTT || '') === '1';
function dbgRt(stage, extra = {}) {
  if (!DEBUG_RTSTT) return;
  console.log(JSON.stringify({ dbg: 'rtstt-core', stage, ...extra }));
}

/**
 * Streaming speech-to-text over the OpenAI Realtime transcription session.
 *
 * The LiveKit sidecar feeds the expert's microphone PCM (resampled to 24 kHz
 * mono) into a `type: "transcription"` realtime session running
 * `gpt-realtime-whisper`. The model streams transcript deltas continuously; the
 * sidecar commits the input audio buffer on the client VAD `audio.endpoint` to
 * close a turn. Deltas surface as `text.partial`, the per-turn `completed`
 * transcript surfaces as `text.final`, both relayed to the Agentium voice
 * gateway which owns persistence, oracle and capture orchestration.
 *
 * Turn boundaries follow OpenAI item ids: every commit finalizes the current
 * item; the next appended audio opens a new one. A fresh item id therefore maps
 * to a fresh Agentium `turn_id`.
 */
export class RealtimeTranscriber {
  constructor(options = {}) {
    this.apiKey = options.apiKey || '';
    this.model = options.model || 'gpt-realtime-whisper';
    this.language = options.language || 'fr';
    this.delay = options.delay || 'low';
    this.prompt = options.prompt || '';
    this.sampleRate = Number(options.sampleRate) || 24000;
    this.apiBase = options.apiBase || 'https://api.openai.com/v1';
    this.WebSocketClass = options.WebSocketClass || globalThis.WebSocket;
    this.onPartial = options.onPartial || (() => {});
    this.onFinal = options.onFinal || (() => {});
    this.onError = options.onError || (() => {});
    this.onMetric = options.onMetric || (() => {});
    this.openTimeoutMs = Number(options.openTimeoutMs) || 8000;

    this.socket = null;
    this.open = false;
    this.closed = false;
    // Map OpenAI item_id -> Agentium turn_id so partial/final share one turn.
    this.itemTurns = new Map();
    this.currentItemId = null;
    this.pendingTurnId = null;
    this.partialText = '';
    // Bytes appended since the last commit; guards against OpenAI's minimum
    // 100 ms buffer rule (24 kHz * 2 bytes * 0.1 s = 4800 bytes).
    this.appendedBytesSinceCommit = 0;
    this.turnStartedAt = 0;
    this.minCommitBytes = Math.floor(this.sampleRate * 2 * 0.1);

    // Sidecar-side silence VAD. gpt-realtime-whisper does NOT support OpenAI
    // turn_detection ("Turn detection is not supported for this transcription
    // model"), so end-of-turn must be detected here from the continuous PCM and
    // drive a manual input_audio_buffer.commit (which yields the per-turn
    // `completed` transcript -> text.final -> oracle). A max-turn guard still
    // commits if silence is never observed (constant background noise).
    this.autoCommitOnSilence = options.autoCommitOnSilence !== false;
    this.silenceMs = Number(options.silenceMs) || 1200;
    this.minSpeechMs = Number(options.minSpeechMs) || 250;
    this.vadThreshold = Number(options.vadThreshold) || 300;
    this.maxTurnMs = Number(options.maxTurnMs) || 15000;
    this.silenceCheckMs = Number(options.silenceCheckMs) || 100;
    this.lastVoiceAt = 0;
    this.windowStartedAt = 0;
    this.voicedMsSinceCommit = 0;
    this.hadSpeechSinceCommit = false;
    this.silenceTimer = null;
  }

  realtimeUrl() {
    const base = String(this.apiBase || 'https://api.openai.com/v1').replace(/\/$/, '');
    const wsBase = base.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:');
    return `${wsBase}/realtime?intent=transcription`;
  }

  sessionConfig() {
    const transcription = { model: this.model, language: this.language };
    if (this.delay) transcription.delay = this.delay;
    if (this.prompt) transcription.prompt = this.prompt;
    return {
      type: 'transcription',
      audio: {
        input: {
          format: { type: 'audio/pcm', rate: this.sampleRate },
          transcription,
          // gpt-realtime-whisper streams deltas natively; turn boundaries are
          // driven by the client VAD via manual input_audio_buffer.commit.
          turn_detection: null,
        },
      },
    };
  }

  async connect() {
    if (!this.apiKey) throw new Error('OPENAI_API_KEY is required for realtime transcription');
    if (typeof this.WebSocketClass !== 'function') {
      throw new Error('Node runtime does not expose a WebSocket client');
    }
    // GA Realtime API: the `OpenAI-Beta: realtime=v1` header selects the retired
    // beta shape (server replies `beta_api_shape_disabled` and closes 4000), so
    // it MUST be omitted. The GA `type: "transcription"` session.update shape is
    // what `sessionConfig()` already sends.
    const socket = new this.WebSocketClass(this.realtimeUrl(), {
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
      },
    });
    this.socket = socket;
    socket.addEventListener('message', (message) => {
      void this.handleMessage(message.data);
    });
    socket.addEventListener('close', () => {
      this.open = false;
    });
    socket.addEventListener('error', () => {
      this.onError(new Error('OpenAI realtime transcription transport error'));
    });
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('OpenAI realtime open timed out')), this.openTimeoutMs);
      socket.addEventListener(
        'open',
        () => {
          clearTimeout(timeout);
          this.open = true;
          this.send({ type: 'session.update', session: this.sessionConfig() });
          resolve();
        },
        { once: true },
      );
      socket.addEventListener(
        'error',
        () => {
          clearTimeout(timeout);
          reject(new Error('OpenAI realtime connection failed'));
        },
        { once: true },
      );
    });
    this._startSilenceWatch();
    return this;
  }

  /** Periodic end-of-turn check driven by the sidecar-side silence VAD. */
  _startSilenceWatch() {
    if (!this.autoCommitOnSilence || this.silenceTimer) return;
    this.silenceTimer = setInterval(() => {
      if (!this.open || !this.hadSpeechSinceCommit) return;
      if (this.appendedBytesSinceCommit < this.minCommitBytes) return;
      const now = Date.now();
      const silent =
        this.voicedMsSinceCommit >= this.minSpeechMs && now - this.lastVoiceAt >= this.silenceMs;
      const longTurn = this.windowStartedAt > 0 && now - this.windowStartedAt >= this.maxTurnMs;
      if (!silent && !longTurn) return;
      this.onMetric('realtime_stt_autocommit', {
        reason: silent ? 'silence' : 'max_turn',
        silence_ms: this.silenceMs,
        voiced_ms: Math.round(this.voicedMsSinceCommit),
      });
      this.commit();
    }, this.silenceCheckMs);
    if (typeof this.silenceTimer.unref === 'function') this.silenceTimer.unref();
  }

  /** RMS energy of an Int16LE PCM frame feeds the silence VAD. */
  _observeEnergy(buffer) {
    if (!this.autoCommitOnSilence) return;
    const samples = buffer.length >> 1;
    if (!samples) return;
    let sum = 0;
    for (let i = 0; i + 1 < buffer.length; i += 2) {
      const s = buffer.readInt16LE(i);
      sum += s * s;
    }
    const rms = Math.sqrt(sum / samples);
    if (DEBUG_RTSTT) {
      this._dbgFrames = (this._dbgFrames || 0) + 1;
      this._dbgMaxRms = Math.max(this._dbgMaxRms || 0, rms);
      if (this._dbgFrames === 1 || this._dbgFrames % 100 === 0) {
        dbgRt('energy', {
          frames: this._dbgFrames,
          rms: Math.round(rms),
          max_rms: Math.round(this._dbgMaxRms),
          threshold: this.vadThreshold,
          had_speech: this.hadSpeechSinceCommit,
          voiced_ms: Math.round(this.voicedMsSinceCommit),
          appended_bytes: this.appendedBytesSinceCommit,
        });
      }
    }
    if (rms >= this.vadThreshold) {
      const nowTs = Date.now();
      this.lastVoiceAt = nowTs;
      if (!this.windowStartedAt) this.windowStartedAt = nowTs;
      this.hadSpeechSinceCommit = true;
      this.voicedMsSinceCommit += (samples / this.sampleRate) * 1000;
    }
  }

  send(message) {
    if (!this.socket || !this.open) return false;
    try {
      this.socket.send(JSON.stringify(message));
      return true;
    } catch (error) {
      this.onError(error);
      return false;
    }
  }

  /** Append a 24 kHz mono Int16LE PCM buffer to the input audio buffer. */
  appendPcm(buffer) {
    if (!buffer || !buffer.length || !this.open) return false;
    if (!this.turnStartedAt) this.turnStartedAt = Date.now();
    this.appendedBytesSinceCommit += buffer.length;
    this._observeEnergy(buffer);
    return this.send({
      type: 'input_audio_buffer.append',
      audio: buffer.toString('base64'),
    });
  }

  /** Close the current turn (client VAD endpoint -> manual commit). */
  commit() {
    dbgRt('commit_called', {
      open: this.open,
      appended_bytes: this.appendedBytesSinceCommit,
      min_commit_bytes: this.minCommitBytes,
      had_speech: this.hadSpeechSinceCommit,
      voiced_ms: Math.round(this.voicedMsSinceCommit),
    });
    if (!this.open) return false;
    if (this.appendedBytesSinceCommit < this.minCommitBytes) {
      // Not enough audio for OpenAI to accept the commit; drop silently so an
      // endpoint on a near-empty buffer never errors the session.
      this.onMetric('realtime_stt_commit_skipped_short_buffer', {
        appended_bytes: this.appendedBytesSinceCommit,
        min_commit_bytes: this.minCommitBytes,
      });
      this.appendedBytesSinceCommit = 0;
      return false;
    }
    this.appendedBytesSinceCommit = 0;
    this.hadSpeechSinceCommit = false;
    this.voicedMsSinceCommit = 0;
    this.windowStartedAt = 0;
    return this.send({ type: 'input_audio_buffer.commit' });
  }

  /** Drop the in-flight buffer + current turn (barge-in / loop restart). */
  clear() {
    this.appendedBytesSinceCommit = 0;
    this.partialText = '';
    this.currentItemId = null;
    this.pendingTurnId = null;
    this.turnStartedAt = 0;
    this.hadSpeechSinceCommit = false;
    this.voicedMsSinceCommit = 0;
    this.windowStartedAt = 0;
    this.lastVoiceAt = 0;
    return this.send({ type: 'input_audio_buffer.clear' });
  }

  turnIdForItem(itemId) {
    const key = itemId || 'pending';
    let turnId = this.itemTurns.get(key);
    if (!turnId) {
      turnId = `rt-${randomUUID()}`;
      this.itemTurns.set(key, turnId);
    }
    return turnId;
  }

  async handleMessage(data) {
    let event = null;
    try {
      const text = typeof data === 'string' ? data : Buffer.from(data).toString('utf8');
      event = JSON.parse(text);
    } catch {
      return;
    }
    const type = String(event?.type || '');
    if (DEBUG_RTSTT && type !== 'conversation.item.input_audio_transcription.delta') {
      // Log every non-delta OpenAI event (delta is high-volume); surfaces
      // committed/created/error/speech_started events that explain a silent turn.
      dbgRt('openai_event', { type, sample: JSON.stringify(event).slice(0, 240) });
    }
    if (type === 'conversation.item.input_audio_transcription.delta') {
      const itemId = event.item_id || this.currentItemId || 'pending';
      if (itemId !== this.currentItemId) {
        // New OpenAI item => new Agentium turn.
        this.currentItemId = itemId;
        this.partialText = '';
        if (!this.turnStartedAt) this.turnStartedAt = Date.now();
      }
      this.partialText += String(event.delta || '');
      const turnId = this.turnIdForItem(itemId);
      this.onPartial(turnId, this.partialText.trim());
      return;
    }
    if (type === 'conversation.item.input_audio_transcription.completed') {
      const itemId = event.item_id || this.currentItemId || 'pending';
      const turnId = this.turnIdForItem(itemId);
      const transcript = String(event.transcript ?? this.partialText ?? '').trim();
      const durationMs = this.turnStartedAt ? Date.now() - this.turnStartedAt : 0;
      this.onFinal(turnId, transcript, durationMs);
      this.itemTurns.delete(itemId);
      this.itemTurns.delete('pending');
      this.currentItemId = null;
      this.partialText = '';
      this.turnStartedAt = 0;
      return;
    }
    if (type === 'error') {
      this.onError(new Error(event?.error?.message || 'OpenAI realtime error'));
    }
  }

  close() {
    this.closed = true;
    this.open = false;
    if (this.silenceTimer) {
      clearInterval(this.silenceTimer);
      this.silenceTimer = null;
    }
    try {
      this.socket?.close?.(1000, 'realtime-stt-close');
    } catch {
      // best-effort close
    }
  }
}
