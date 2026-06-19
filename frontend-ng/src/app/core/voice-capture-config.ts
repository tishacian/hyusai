export type VoiceCaptureMode = 'normal' | 'robust' | 'manual_safe';

export interface VoiceCaptureRawConfig {
  capture_mode?: VoiceCaptureMode | string | null;
  auto_capture_mode_enabled?: boolean;
  auto_endpoint?: boolean;
  silence_ms?: number;
  dictation_silence_ms?: number;
  min_speech_ms?: number;
  dictation_min_speech_ms?: number;
  max_turn_ms?: number;
  rms_threshold?: number;
  endpoint_grace_ms?: number;
  vad_hangover_ms?: number;
  vad_calibration_ms?: number;
  vad_min_silence_frames_ms?: number;
}

export interface VoiceCaptureDefaults {
  auto_endpoint: boolean;
  silence_ms: number;
  dictation_silence_ms: number;
  min_speech_ms: number;
  dictation_min_speech_ms: number;
  max_turn_ms: number;
  rms_threshold: number;
  endpoint_grace_ms: number;
  vad_hangover_ms: number;
  vad_calibration_ms: number;
  vad_min_silence_frames_ms: number;
}

export interface ResolvedVoiceCaptureConfig extends VoiceCaptureDefaults {
  capture_mode: VoiceCaptureMode;
  auto_capture_mode_enabled: boolean;
}

export interface VoiceCaptureStorageParts {
  surface: 'chat' | 'knowledge_capture';
  workspaceSlug?: string | null;
  profileKey?: string | null;
}

export const DEFAULT_VOICE_CAPTURE_CONFIG: VoiceCaptureDefaults = {
  auto_endpoint: true,
  silence_ms: 1200,
  dictation_silence_ms: 2000,
  min_speech_ms: 350,
  dictation_min_speech_ms: 300,
  max_turn_ms: 45000,
  rms_threshold: 0.018,
  endpoint_grace_ms: 0,
  vad_hangover_ms: 0,
  vad_calibration_ms: 300,
  vad_min_silence_frames_ms: 0,
};

const ROBUST_PRESET = {
  silence_ms: 2200,
  dictation_silence_ms: 2600,
  min_speech_ms: 700,
  dictation_min_speech_ms: 700,
  max_turn_ms: 12000,
  rms_threshold: 0.012,
  endpoint_grace_ms: 650,
  vad_hangover_ms: 350,
  vad_min_silence_frames_ms: 250,
};

export function normalizeVoiceCaptureMode(value: unknown, fallback: VoiceCaptureMode = 'normal'): VoiceCaptureMode {
  return value === 'robust' || value === 'manual_safe' || value === 'normal' ? value : fallback;
}

export function voiceCaptureStorageKey(parts: VoiceCaptureStorageParts): string {
  const workspace = slugPart(parts.workspaceSlug || 'workspace');
  const profile = slugPart(parts.profileKey || 'default');
  return `agentium.voice.capture_mode.${parts.surface}.${workspace}.${profile}`;
}

export function resolveVoiceCaptureConfig(
  raw: VoiceCaptureRawConfig | null | undefined,
  modeOverride: VoiceCaptureMode | null | undefined,
  defaults: Partial<VoiceCaptureDefaults> = {},
): ResolvedVoiceCaptureConfig {
  const mergedDefaults = { ...DEFAULT_VOICE_CAPTURE_CONFIG, ...defaults };
  const captureMode = normalizeVoiceCaptureMode(modeOverride || raw?.capture_mode || 'normal');
  const resolved: ResolvedVoiceCaptureConfig = {
    capture_mode: captureMode,
    auto_capture_mode_enabled: raw?.auto_capture_mode_enabled === true,
    auto_endpoint: raw?.auto_endpoint !== false && mergedDefaults.auto_endpoint,
    silence_ms: intValue(raw?.silence_ms, mergedDefaults.silence_ms, 300, 30000),
    dictation_silence_ms: intValue(raw?.dictation_silence_ms, mergedDefaults.dictation_silence_ms, 300, 30000),
    min_speech_ms: intValue(raw?.min_speech_ms, mergedDefaults.min_speech_ms, 100, 3000),
    dictation_min_speech_ms: intValue(raw?.dictation_min_speech_ms, mergedDefaults.dictation_min_speech_ms, 100, 3000),
    max_turn_ms: intValue(raw?.max_turn_ms, mergedDefaults.max_turn_ms, 5000, 600000),
    rms_threshold: floatValue(raw?.rms_threshold, mergedDefaults.rms_threshold, 0.001, 0.15),
    endpoint_grace_ms: intValue(raw?.endpoint_grace_ms, mergedDefaults.endpoint_grace_ms, 0, 3000),
    vad_hangover_ms: intValue(raw?.vad_hangover_ms, mergedDefaults.vad_hangover_ms, 0, 2000),
    vad_calibration_ms: intValue(raw?.vad_calibration_ms, mergedDefaults.vad_calibration_ms, 0, 3000),
    vad_min_silence_frames_ms: intValue(
      raw?.vad_min_silence_frames_ms,
      mergedDefaults.vad_min_silence_frames_ms,
      0,
      2000,
    ),
  };

  if (captureMode === 'robust' || captureMode === 'manual_safe') {
    resolved.silence_ms = Math.max(resolved.silence_ms, ROBUST_PRESET.silence_ms);
    resolved.dictation_silence_ms = Math.max(resolved.dictation_silence_ms, ROBUST_PRESET.dictation_silence_ms);
    resolved.min_speech_ms = Math.max(resolved.min_speech_ms, ROBUST_PRESET.min_speech_ms);
    resolved.dictation_min_speech_ms = Math.max(
      resolved.dictation_min_speech_ms,
      ROBUST_PRESET.dictation_min_speech_ms,
    );
    resolved.rms_threshold = Math.min(resolved.rms_threshold, ROBUST_PRESET.rms_threshold);
    resolved.endpoint_grace_ms = Math.max(resolved.endpoint_grace_ms, ROBUST_PRESET.endpoint_grace_ms);
    resolved.vad_hangover_ms = Math.max(resolved.vad_hangover_ms, ROBUST_PRESET.vad_hangover_ms);
    resolved.vad_min_silence_frames_ms = Math.max(
      resolved.vad_min_silence_frames_ms,
      ROBUST_PRESET.vad_min_silence_frames_ms,
    );
  }
  if (captureMode === 'robust') {
    resolved.max_turn_ms = Math.min(resolved.max_turn_ms, ROBUST_PRESET.max_turn_ms);
  }
  if (captureMode === 'manual_safe') {
    resolved.auto_endpoint = false;
  }
  return resolved;
}

function intValue(value: unknown, fallback: number, min: number, max: number): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.min(max, Math.max(min, Math.round(numeric)));
}

function floatValue(value: unknown, fallback: number, min: number, max: number): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.min(max, Math.max(min, numeric));
}

function slugPart(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80) || 'default';
}
