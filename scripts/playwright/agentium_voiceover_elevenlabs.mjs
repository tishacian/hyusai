#!/usr/bin/env node
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(__dirname, '../..');
const API_BASE = 'https://api.elevenlabs.io/v1';

function arg(name, fallback = null) {
  const prefix = `--${name}=`;
  const found = process.argv.find((item) => item.startsWith(prefix));
  if (found) return found.slice(prefix.length);
  return fallback;
}

function hasFlag(name) {
  return process.argv.includes(`--${name}`);
}

function run(command, args) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    child.on('close', (status) => resolve({ status, stdout, stderr, ok: status === 0 }));
  });
}

async function requestJson(pathname, apiKey) {
  const res = await fetch(`${API_BASE}${pathname}`, {
    headers: { 'xi-api-key': apiKey },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(`ElevenLabs ${pathname} failed ${res.status}: ${JSON.stringify(body).slice(0, 400)}`);
  }
  return body;
}

async function listVoices(apiKey) {
  const body = await requestJson('/voices', apiKey);
  return Array.isArray(body.voices) ? body.voices : [];
}

function chooseVoice(voices, { voiceId, voiceName }) {
  if (voiceId) {
    const found = voices.find((voice) => voice.voice_id === voiceId);
    return found || { voice_id: voiceId, name: voiceName || voiceId };
  }
  if (voiceName) {
    const lower = voiceName.toLowerCase();
    const found = voices.find((voice) => String(voice.name || '').toLowerCase() === lower)
      || voices.find((voice) => String(voice.name || '').toLowerCase().includes(lower));
    if (found) return found;
  }
  const french = voices.find((voice) => {
    const labels = voice.labels || {};
    const haystack = [
      voice.name,
      labels.language,
      labels.accent,
      labels.description,
      labels.use_case,
    ].filter(Boolean).join(' ').toLowerCase();
    return /\bfr\b|french|franc/.test(haystack);
  });
  return french || voices[0] || null;
}

function voiceSettings() {
  const settings = {
    stability: Number(arg('stability', process.env.ELEVENLABS_STABILITY || '0.45')),
    similarity_boost: Number(arg('similarity', process.env.ELEVENLABS_SIMILARITY || '0.78')),
    style: Number(arg('style', process.env.ELEVENLABS_STYLE || '0.28')),
    use_speaker_boost: !hasFlag('no-speaker-boost'),
  };
  const speed = arg('speed', process.env.ELEVENLABS_SPEED || null);
  if (speed !== null) settings.speed = Number(speed);
  return settings;
}

async function synthesizeSegment({ apiKey, voiceId, modelId, outputFormat, text, outFile }) {
  const url = `${API_BASE}/text-to-speech/${encodeURIComponent(voiceId)}?output_format=${encodeURIComponent(outputFormat)}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Accept': 'audio/mpeg',
      'Content-Type': 'application/json',
      'xi-api-key': apiKey,
    },
    body: JSON.stringify({
      text,
      model_id: modelId,
      voice_settings: voiceSettings(),
    }),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`TTS failed ${res.status}: ${body.slice(0, 500)}`);
  }
  const audio = Buffer.from(await res.arrayBuffer());
  await writeFile(outFile, audio);
  return { ok: true, bytes: audio.length, status: res.status };
}

async function buildCombinedVoiceover(outDir, segmentFiles, silenceSec) {
  if (segmentFiles.length === 0) return null;
  const output = path.join(outDir, 'voiceover.wav');
  const args = ['-y'];
  const filterParts = [];
  const labels = [];
  let inputIndex = 0;
  for (let idx = 0; idx < segmentFiles.length; idx += 1) {
    args.push('-i', segmentFiles[idx]);
    filterParts.push(
      `[${inputIndex}:a]aresample=48000,aformat=sample_fmts=s16:channel_layouts=mono[a${idx}]`,
    );
    labels.push(`[a${idx}]`);
    inputIndex += 1;
    if (idx < segmentFiles.length - 1 && silenceSec > 0) {
      args.push('-f', 'lavfi', '-t', String(silenceSec), '-i', 'anullsrc=channel_layout=mono:sample_rate=48000');
      filterParts.push(`[${inputIndex}:a]aformat=sample_fmts=s16:channel_layouts=mono[s${idx}]`);
      labels.push(`[s${idx}]`);
      inputIndex += 1;
    }
  }
  filterParts.push(`${labels.join('')}concat=n=${labels.length}:v=0:a=1[out]`);
  args.push('-filter_complex', filterParts.join(';'), '-map', '[out]', '-c:a', 'pcm_s16le', output);
  const ffmpeg = await run('ffmpeg', args);
  return { output, ffmpeg, ok: ffmpeg.ok };
}

async function main() {
  const apiKey = process.env.ELEVENLABS_API_KEY || '';
  if (!apiKey) {
    throw new Error('ELEVENLABS_API_KEY is required. Export it in your shell; do not commit it.');
  }

  const requestedVoiceId = arg('voice-id', process.env.ELEVENLABS_VOICE_ID || null);
  const requestedVoiceName = arg('voice-name', process.env.ELEVENLABS_VOICE_NAME || null);
  const voices = requestedVoiceId && !hasFlag('list-voices') ? [] : await listVoices(apiKey);
  if (hasFlag('list-voices')) {
    for (const voice of voices) {
      const labels = voice.labels || {};
      console.log(`${voice.name}\t${voice.voice_id}\t${labels.language || ''}\t${labels.accent || ''}\t${labels.use_case || ''}`);
    }
    return;
  }

  const scriptPath = path.resolve(arg('script', process.env.VOICEOVER_SCRIPT || path.join(__dirname, 'agentium_voiceover_script.json')));
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const outDir = path.resolve(arg('out-dir', process.env.OUT_DIR || path.join(repo, 'docs/video-captures', `voiceover-elevenlabs-${stamp}`)));
  const modelId = arg('model', process.env.ELEVENLABS_MODEL_ID || 'eleven_multilingual_v2');
  const outputFormat = arg('format', process.env.ELEVENLABS_OUTPUT_FORMAT || 'mp3_44100_128');
  const silenceSec = Number(arg('silence', process.env.VOICEOVER_SILENCE_SEC || '0.75'));
  const voice = chooseVoice(voices, {
    voiceId: requestedVoiceId,
    voiceName: requestedVoiceName,
  });
  if (!voice?.voice_id) {
    throw new Error('No ElevenLabs voice available. Pass --voice-id=<id> or --voice-name=<name>.');
  }
  await mkdir(outDir, { recursive: true });

  const segments = JSON.parse(await readFile(scriptPath, 'utf8'));
  const manifest = {
    startedAt: new Date().toISOString(),
    provider: 'elevenlabs',
    scriptPath,
    outDir,
    modelId,
    outputFormat,
    voice: {
      id: voice.voice_id,
      name: voice.name || voice.voice_id,
      labels: voice.labels || {},
    },
    voiceSettings: voiceSettings(),
    silenceSec,
    segments: [],
  };

  for (const segment of segments) {
    const id = String(segment.id || `segment-${manifest.segments.length + 1}`).replace(/[^a-zA-Z0-9._-]/g, '-');
    const mp3 = path.join(outDir, `${id}.mp3`);
    const entry = {
      id,
      text: segment.text || '',
      characterCount: String(segment.text || '').length,
      mp3,
    };
    try {
      const result = await synthesizeSegment({
        apiKey,
        voiceId: voice.voice_id,
        modelId,
        outputFormat,
        text: segment.text || '',
        outFile: mp3,
      });
      entry.ok = true;
      entry.bytes = result.bytes;
      entry.status = result.status;
    } catch (err) {
      entry.ok = false;
      entry.error = err.message;
    }
    manifest.segments.push(entry);
    console.log(`${entry.ok ? 'OK' : 'FAIL'} ${id}`);
  }

  const segmentFiles = manifest.segments
    .filter((segment) => segment.ok && segment.mp3)
    .map((segment) => segment.mp3);
  manifest.combined = await buildCombinedVoiceover(outDir, segmentFiles, silenceSec);

  const manifestPath = path.join(outDir, 'voiceover-manifest.json');
  await writeFile(manifestPath, JSON.stringify(manifest, null, 2));
  const failed = manifest.segments.filter((segment) => !segment.ok).length;
  console.log(`ElevenLabs voiceover complete: ${manifest.segments.length - failed} ok / ${failed} failed`);
  console.log(`Voice: ${manifest.voice.name} (${manifest.voice.id})`);
  console.log(`Manifest: ${manifestPath}`);
  process.exit(failed > 0 || !manifest.combined?.ok ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
