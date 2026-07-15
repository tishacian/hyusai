import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { WorkspaceChangedDuringTransportError } from '@app/core/livekit-conversation.service';
import { KnowledgeCaptureComponent } from './knowledge-capture.component';

interface Deferred<T> {
  readonly promise: Promise<T>;
  readonly resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

test('a resolved LiveKit A connection is closed before the consumer can fallback under B', async () => {
  const lateConnection = deferred<any>();
  let workspaceSlug = 'andritz';
  let workspaceEpoch = 1;
  let backendOpenCalls = 0;
  let closeCalls = 0;
  const component = Object.create(KnowledgeCaptureComponent.prototype) as any;

  component.workspace = {
    captureRequestScope: () => Object.freeze({
      workspaceSlug,
      epoch: workspaceEpoch,
    }),
    isRequestScopeCurrent: (scope: { workspaceSlug: string; epoch: number }) => (
      scope.workspaceSlug === workspaceSlug && scope.epoch === workspaceEpoch
    ),
  };
  component.voiceCaptureGeneration = 4;
  component.voiceWorkspaceGeneration = 2;
  component.voiceConnection = null;
  component.conversationMode = () => 'conversation_only';
  component.shouldPreferLiveKitTransport = () => true;
  component.voiceOracleSessionOptions = () => ({});
  component.selectedDomain = 'industrial';
  component.contextId = '';
  component.systemId = '';
  component.setVoiceNotice = () => undefined;
  component.livekitConversation = { open: () => lateConnection.promise };
  component.voiceSession = {
    open: () => {
      backendOpenCalls += 1;
      throw new Error('stale backend fallback must not open');
    },
  };

  const opening = component.ensureVoiceConnection({
    id: 'session-a',
    voice_runtime: 'livekit',
  });
  workspaceSlug = 'sentinel-ci';
  workspaceEpoch += 1;
  component.voiceWorkspaceGeneration += 1;
  lateConnection.resolve({
    close: () => {
      closeCalls += 1;
    },
  });

  await assert.rejects(
    opening,
    (error: unknown) => error instanceof WorkspaceChangedDuringTransportError,
  );
  assert.equal(closeCalls, 1);
  assert.equal(backendOpenCalls, 0);
  assert.equal(component.voiceConnection, null);
});

test('workspace reset during microphone enable cannot rearm capture in B', async () => {
  const microphoneEnabled = deferred<void>();
  let workspaceSlug = 'andritz';
  let workspaceEpoch = 1;
  let enableCalls = 0;
  let audioStreamCalls = 0;
  let recorderStarts = 0;
  const component = Object.create(KnowledgeCaptureComponent.prototype) as any;

  component.workspace = {
    captureRequestScope: () => Object.freeze({ workspaceSlug, epoch: workspaceEpoch }),
    isRequestScopeCurrent: (scope: { workspaceSlug: string; epoch: number }) => (
      scope.workspaceSlug === workspaceSlug && scope.epoch === workspaceEpoch
    ),
  };
  component.voiceWorkspaceGeneration = 3;
  component.recording = () => false;
  component.transcribing = () => false;
  component.clearAutoResumeTimer = () => undefined;
  component.session = () => ({ id: 'session-a' });
  component.realtimeSttActive = true;
  component.ensureVoiceConnection = async () => ({
    enableMicrophone: () => {
      enableCalls += 1;
      return microphoneEnabled.promise;
    },
  });
  component.ensureAudioStream = async () => {
    audioStreamCalls += 1;
    return true;
  };
  component.startAudioRecorder = () => {
    recorderStarts += 1;
    return true;
  };

  const starting = component.startRecordingTurn();
  for (let attempt = 0; attempt < 10 && enableCalls === 0; attempt += 1) {
    await Promise.resolve();
  }
  assert.equal(enableCalls, 1);

  workspaceSlug = 'sentinel-ci';
  workspaceEpoch += 1;
  component.voiceWorkspaceGeneration += 1;
  microphoneEnabled.resolve();
  await starting;

  assert.equal(audioStreamCalls, 0);
  assert.equal(recorderStarts, 0);
});
