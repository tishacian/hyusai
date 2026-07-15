import '@angular/compiler';
import test from 'node:test';
import assert from 'node:assert/strict';
import { VoiceLoopController } from './voice-loop-controller.service';

class RecorderStub {
  static constructed = 0;
  static isTypeSupported(): boolean {
    return true;
  }

  state: RecordingState = 'inactive';
  ondataavailable: ((event: BlobEvent) => void) | null = null;
  onstop: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(_stream: MediaStream, _options?: MediaRecorderOptions) {
    RecorderStub.constructed += 1;
  }

  start(): void {
    this.state = 'recording';
  }

  stop(): void {
    this.state = 'inactive';
    this.ondataavailable?.({ data: new Blob(['audio-a'], { type: 'audio/webm' }) } as BlobEvent);
    this.onstop?.(new Event('stop'));
  }
}

function stream(onStop: () => void = () => {}): MediaStream {
  return {
    getTracks: () => [{ stop: onStop }],
  } as unknown as MediaStream;
}

function installRecorder(): () => void {
  const previous = globalThis.MediaRecorder;
  RecorderStub.constructed = 0;
  Object.defineProperty(globalThis, 'MediaRecorder', {
    configurable: true,
    value: RecorderStub,
  });
  return () => {
    if (previous) {
      Object.defineProperty(globalThis, 'MediaRecorder', { configurable: true, value: previous });
    } else {
      Reflect.deleteProperty(globalThis, 'MediaRecorder');
    }
  };
}

test('dispose discards recorder A without emitting a final chunk or endpoint', async () => {
  const restore = installRecorder();
  try {
    const controller = new VoiceLoopController('chat');
    let chunks = 0;
    let endpoints = 0;
    await controller.startTurn({
      stream: stream(),
      onChunk: () => { chunks += 1; },
      onEndpoint: () => { endpoints += 1; },
    });

    controller.dispose();

    assert.equal(chunks, 0, 'the stop flush from recorder A is discarded');
    assert.equal(endpoints, 0, 'discard-style dispose cannot trigger transcription');
    assert.equal(controller.recording(), false);
    assert.equal(controller.state(), 'idle');
  } finally {
    restore();
  }
});

test('hard stop invalidates a getUserMedia request still arming in workspace A', async () => {
  const restoreRecorder = installRecorder();
  const previousNavigator = globalThis.navigator;
  let resolveStream!: (value: MediaStream) => void;
  const pendingStream = new Promise<MediaStream>((resolve) => {
    resolveStream = resolve;
  });
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: { mediaDevices: { getUserMedia: () => pendingStream } },
  });
  let trackStops = 0;
  try {
    const controller = new VoiceLoopController('chat');
    let endpoints = 0;
    const started = controller.startTurn({ onEndpoint: () => { endpoints += 1; } });

    controller.hardStop();
    resolveStream(stream(() => { trackStops += 1; }));

    assert.equal(await started, false);
    assert.equal(RecorderStub.constructed, 0, 'no recorder may be created in workspace B');
    assert.equal(trackStops, 1, 'the late A stream is released immediately');
    assert.equal(endpoints, 0);
  } finally {
    restoreRecorder();
    if (previousNavigator) {
      Object.defineProperty(globalThis, 'navigator', { configurable: true, value: previousNavigator });
    } else {
      Reflect.deleteProperty(globalThis, 'navigator');
    }
  }
});

test('normal endpoint still flushes audio and calls onEndpoint once', async () => {
  const restore = installRecorder();
  try {
    const controller = new VoiceLoopController('chat');
    let chunks = 0;
    let endpoints = 0;
    await controller.startTurn({
      stream: stream(),
      onChunk: () => { chunks += 1; },
      onEndpoint: () => { endpoints += 1; },
    });

    controller.stopTurn('manual', true);

    assert.equal(chunks, 1);
    assert.equal(endpoints, 1);
  } finally {
    restore();
  }
});
