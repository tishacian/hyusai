import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Subject } from 'rxjs';
import { VoiceTtsPlaybackController } from './voice-tts-playback.service';

interface Deferred<T> {
  readonly promise: Promise<T>;
  readonly resolve: (value: T) => void;
  readonly reject: (error: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

test('a rejected play promise from workspace A cannot advance or finish the B queue', async () => {
  const previousAudio = globalThis.Audio;
  const previousCreateObjectUrl = URL.createObjectURL;
  const previousRevokeObjectUrl = URL.revokeObjectURL;
  const playAttempts: Array<Deferred<void>> = [];
  const syntheses: Array<Subject<Blob>> = [];
  let objectUrlSequence = 0;

  class AudioStub {
    currentTime = 0;
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    readonly playAttempt = deferred<void>();

    constructor(readonly src: string) {
      playAttempts.push(this.playAttempt);
    }

    play(): Promise<void> {
      return this.playAttempt.promise;
    }

    pause(): void {}
  }

  Object.defineProperty(globalThis, 'Audio', {
    configurable: true,
    value: AudioStub,
  });
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: () => `blob:test-${++objectUrlSequence}`,
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: () => undefined,
  });

  const api = {
    synthesizeSpeech: () => {
      const request = new Subject<Blob>();
      syntheses.push(request);
      return request.asObservable();
    },
  };
  let workspaceBEnded = 0;
  const controller = new VoiceTtsPlaybackController('test', api as never);

  try {
    controller.playText('Workspace A private answer.', { surface: 'chat-a' });
    syntheses[0].next(new Blob(['a'], { type: 'audio/mpeg' }));
    assert.equal(controller.state(), 'speaking');

    controller.reset(true);
    controller.playText('Workspace B answer.', {
      surface: 'chat-b',
      onEnded: () => workspaceBEnded += 1,
    });
    syntheses[1].next(new Blob(['b'], { type: 'audio/mpeg' }));
    assert.equal(controller.state(), 'speaking');

    playAttempts[0].reject(new Error('late autoplay rejection from A'));
    await Promise.resolve();
    await Promise.resolve();

    assert.equal(controller.state(), 'speaking');
    assert.equal(controller.isSpeaking(), true);
    assert.equal(workspaceBEnded, 0);
  } finally {
    controller.reset(true);
    playAttempts.forEach((attempt) => attempt.resolve());
    if (previousAudio) {
      Object.defineProperty(globalThis, 'Audio', {
        configurable: true,
        value: previousAudio,
      });
    } else {
      Reflect.deleteProperty(globalThis, 'Audio');
    }
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: previousCreateObjectUrl,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: previousRevokeObjectUrl,
    });
  }
});
