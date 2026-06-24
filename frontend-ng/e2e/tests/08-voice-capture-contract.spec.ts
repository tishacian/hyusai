import '@angular/compiler';
import { expect, test } from '@playwright/test';
import {
  resolveVoiceCaptureConfig,
  type VoiceCaptureRawConfig,
} from '../../src/app/core/voice-capture-config';
import { detectVoiceCommand } from '../../src/app/core/voice-command-detector';
import { VoiceLoopController, type VoiceLoopTurnConfig } from '../../src/app/core/voice-loop-controller.service';

function fakeRecordingRecorder() {
  let requestDataCount = 0;
  let stopCount = 0;
  return {
    recorder: {
      state: 'recording',
      requestData: () => {
        requestDataCount += 1;
      },
      stop: () => {
        stopCount += 1;
      },
    },
    counts: () => ({ requestDataCount, stopCount }),
  };
}

test.describe('voice capture VAD contract', () => {
  test('robust capture keeps conservative timing while lowering only the RMS threshold', () => {
    const raw: VoiceCaptureRawConfig = {
      capture_mode: 'normal',
      auto_endpoint: true,
      silence_ms: 3200,
      dictation_silence_ms: 4200,
      min_speech_ms: 850,
      dictation_min_speech_ms: 900,
      max_turn_ms: 25000,
      rms_threshold: 0.02,
      endpoint_grace_ms: 900,
      vad_hangover_ms: 500,
      vad_calibration_ms: 450,
      vad_min_silence_frames_ms: 300,
    };

    const resolved = resolveVoiceCaptureConfig(raw, 'robust');

    expect(resolved.capture_mode).toBe('robust');
    expect(resolved.auto_endpoint).toBe(true);
    expect(resolved.silence_ms).toBe(3200);
    expect(resolved.dictation_silence_ms).toBe(4200);
    expect(resolved.min_speech_ms).toBe(850);
    expect(resolved.dictation_min_speech_ms).toBe(900);
    expect(resolved.max_turn_ms).toBe(25000);
    expect(resolved.rms_threshold).toBe(0.012);
    expect(resolved.endpoint_grace_ms).toBe(900);
    expect(resolved.vad_hangover_ms).toBe(500);
    expect(resolved.vad_calibration_ms).toBe(450);
    expect(resolved.vad_min_silence_frames_ms).toBe(300);

    expect(resolveVoiceCaptureConfig({ rms_threshold: 0.008 }, 'robust').rms_threshold).toBe(0.008);
  });

  test('manual safe mode disables auto endpoint but keeps robust VAD safeguards', () => {
    const resolved = resolveVoiceCaptureConfig(
      {
        auto_endpoint: true,
        silence_ms: 900,
        min_speech_ms: 350,
        endpoint_grace_ms: 0,
        vad_hangover_ms: 0,
        vad_min_silence_frames_ms: 0,
      },
      'manual_safe',
    );

    expect(resolved.capture_mode).toBe('manual_safe');
    expect(resolved.auto_endpoint).toBe(false);
    expect(resolved.silence_ms).toBe(2200);
    expect(resolved.dictation_silence_ms).toBe(2600);
    expect(resolved.min_speech_ms).toBe(700);
    expect(resolved.endpoint_grace_ms).toBe(650);
    expect(resolved.vad_hangover_ms).toBe(350);
    expect(resolved.vad_min_silence_frames_ms).toBe(250);
  });

  test('a resumed voice cancels a silence endpoint candidate during grace', async () => {
    const controller = new VoiceLoopController('vad-cancel-contract') as any;
    const fake = fakeRecordingRecorder();
    controller.recorder = fake.recorder;
    const metrics: Record<string, unknown>[] = [];
    const config: VoiceLoopTurnConfig = {
      captureMode: 'robust',
      silenceMs: 2200,
      minSpeechMs: 700,
      onMetric: (payload) => metrics.push(payload),
    };

    controller.scheduleEndpointCandidate(config, 20, { since_voice_ms: 2300, rms: 0.004, threshold: 0.012 });
    controller.cancelEndpointCandidate(config, 'voice_resumed');
    await new Promise((resolve) => setTimeout(resolve, 35));

    expect(fake.counts()).toEqual({ requestDataCount: 1, stopCount: 0 });
    expect(metrics.map((entry) => entry['metric'])).toEqual(['endpoint_candidate', 'endpoint_cancelled']);
    expect(metrics[0]).toMatchObject({
      metric: 'endpoint_candidate',
      capture_mode: 'robust',
      endpoint_reason: 'silence',
      silence_ms: 2200,
      min_speech_ms: 700,
      endpoint_grace_ms: 20,
    });
    expect(metrics[1]).toMatchObject({
      metric: 'endpoint_cancelled',
      capture_mode: 'robust',
      endpoint_reason: 'voice_resumed',
      cancelled: true,
    });
  });

  test('a confirmed silence endpoint flushes recorder data before stopping the turn', () => {
    const controller = new VoiceLoopController('vad-confirm-contract') as any;
    const fake = fakeRecordingRecorder();
    controller.recorder = fake.recorder;
    const metrics: Record<string, unknown>[] = [];
    const config: VoiceLoopTurnConfig = {
      captureMode: 'normal',
      silenceMs: 1200,
      minSpeechMs: 350,
      onMetric: (payload) => metrics.push(payload),
    };

    controller.scheduleEndpointCandidate(config, 0, { since_voice_ms: 1300, rms: 0.003, threshold: 0.018 });

    expect(fake.counts()).toEqual({ requestDataCount: 2, stopCount: 1 });
    expect(metrics.map((entry) => entry['metric'])).toEqual(['endpoint_candidate', 'endpoint_confirmed']);
    expect(metrics[1]).toMatchObject({
      metric: 'endpoint_confirmed',
      capture_mode: 'normal',
      endpoint_reason: 'silence',
    });
  });

  test('long continuous speech flushes audio at max turn without becoming no-speech', async () => {
    const originalMediaRecorder = (globalThis as any).MediaRecorder;
    const originalWindow = (globalThis as any).window;
    const originalRequestAnimationFrame = (globalThis as any).requestAnimationFrame;
    const originalCancelAnimationFrame = (globalThis as any).cancelAnimationFrame;
    let requestDataCount = 0;
    let stopCount = 0;

    class FakeMediaRecorder {
      static isTypeSupported() {
        return true;
      }

      state: 'inactive' | 'recording' = 'inactive';
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;

      constructor(_stream: MediaStream, _options?: MediaRecorderOptions) {}

      start(_timesliceMs?: number) {
        this.state = 'recording';
      }

      requestData() {
        requestDataCount += 1;
        this.ondataavailable?.({
          data: new Blob(['continuous speech frame'], { type: 'audio/webm' }),
        });
      }

      stop() {
        if (this.state !== 'recording') return;
        stopCount += 1;
        this.state = 'inactive';
        this.onstop?.();
      }
    }

    class FakeAnalyser {
      fftSize = 1024;
      smoothingTimeConstant = 0;
      private frameCount = 0;

      getByteTimeDomainData(data: Uint8Array) {
        this.frameCount += 1;
        const amplitude = this.frameCount <= 2 ? 1 : 127;
        for (let i = 0; i < data.length; i += 1) {
          data[i] = i % 2 === 0 ? 128 + amplitude : 128 - amplitude;
        }
      }
    }

    class FakeAudioContext {
      state: AudioContextState = 'running';

      createAnalyser() {
        return new FakeAnalyser();
      }

      createMediaStreamSource(_stream: MediaStream) {
        return {
          connect: (_node: unknown) => undefined,
          disconnect: () => undefined,
        };
      }

      async close() {
        this.state = 'closed';
      }
    }

    const controller = new VoiceLoopController('vad-max-turn-contract');
    const endpoints: { blob: Blob; reason: string }[] = [];
    const notices: (string | null)[] = [];
    const states: string[] = [];

    try {
      (globalThis as any).MediaRecorder = FakeMediaRecorder;
      (globalThis as any).window = {
        ...(originalWindow || {}),
        AudioContext: FakeAudioContext,
        webkitAudioContext: FakeAudioContext,
      };
      (globalThis as any).requestAnimationFrame = (callback: FrameRequestCallback) =>
        setTimeout(() => callback(performance.now()), 40);
      (globalThis as any).cancelAnimationFrame = (id: ReturnType<typeof setTimeout>) => clearTimeout(id);

      const started = await controller.startTurn({
        autoEndpoint: true,
        captureMode: 'normal',
        maxTurnMs: 300,
        minSpeechMs: 50,
        vadCalibrationMs: 0,
        stream: { getTracks: () => [] } as unknown as MediaStream,
        releaseStreamOnStop: false,
        onEndpoint: (blob, reason) => endpoints.push({ blob, reason }),
        onNotice: (notice) => notices.push(notice),
        onState: (state) => states.push(state),
      });

      expect(started).toBe(true);
      await expect.poll(() => endpoints.length, { timeout: 1000 }).toBe(1);

      expect(endpoints[0].reason).toBe('max_turn');
      expect(endpoints[0].blob.size).toBeGreaterThan(0);
      expect(requestDataCount).toBeGreaterThanOrEqual(1);
      expect(stopCount).toBe(1);
      expect(notices).toContain('Max voice turn reached');
      expect(notices).not.toContain('No speech detected');
      expect(states).toContain('endpointing');
    } finally {
      controller.dispose();
      (globalThis as any).MediaRecorder = originalMediaRecorder;
      (globalThis as any).window = originalWindow;
      (globalThis as any).requestAnimationFrame = originalRequestAnimationFrame;
      (globalThis as any).cancelAnimationFrame = originalCancelAnimationFrame;
    }
  });
});

test.describe('voice command detector contract', () => {
  const settings = { commands_enabled: true, command_packs: ['generic'] };

  test('command-like content is not treated as a capture stop command', () => {
    expect(detectVoiceCommand('fin de session', settings, 'knowledge_capture')).toBe('stop');
    expect(detectVoiceCommand("C'est la fin de session", settings, 'knowledge_capture')).toBe('stop');
    expect(detectVoiceCommand('assistant fin de session', { ...settings, trigger_word: 'assistant' }, 'knowledge_capture')).toBe('stop');

    expect(
      detectVoiceCommand(
        'Dans le rapport, la fin de session doit mentionner le nettoyage du convoyeur.',
        settings,
        'knowledge_capture',
      ),
    ).toBeNull();
    expect(
      detectVoiceCommand(
        'On explique ici que la fin de session ne veut pas dire arret machine.',
        settings,
        'chat',
      ),
    ).toBeNull();
  });

  test('turn and section commands require a command-shaped utterance', () => {
    expect(detectVoiceCommand('tour suivant', settings, 'knowledge_capture')).toBe('end_turn');
    expect(detectVoiceCommand('bon section suivante', settings, 'knowledge_capture')).toBe('end_section');
    expect(detectVoiceCommand('on passe a la suite merci', settings, 'knowledge_capture')).toBe('end_section');

    expect(
      detectVoiceCommand(
        'Dans la section suivante on decrit le reglage de pression.',
        settings,
        'knowledge_capture',
      ),
    ).toBeNull();
    expect(
      detectVoiceCommand(
        'Le point suivant du rapport doit rester dans le meme paragraphe.',
        settings,
        'knowledge_capture',
      ),
    ).toBeNull();
  });
});
