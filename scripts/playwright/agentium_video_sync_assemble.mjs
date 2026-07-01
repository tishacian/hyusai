#!/usr/bin/env node
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import path from 'node:path';

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

async function probeDuration(file) {
  const result = await run('ffprobe', [
    '-v',
    'error',
    '-show_entries',
    'format=duration',
    '-of',
    'default=noprint_wrappers=1:nokey=1',
    file,
  ]);
  const value = Number(result.stdout.trim());
  return result.ok && Number.isFinite(value) && value > 0 ? value : null;
}

async function readJson(file) {
  return JSON.parse(await readFile(path.resolve(file), 'utf8'));
}

function safeSceneResults(manifest) {
  return (manifest.results || [])
    .filter((row) => row.id !== 'continuous-video-save')
    .filter((row) => row.ok !== false && row.startedAtMs && row.endedAtMs && row.endedAtMs > row.startedAtMs);
}

async function audioTargets(voiceManifest, sceneCount) {
  const silenceSec = Number(voiceManifest.silenceSec || 0);
  const segments = (voiceManifest.segments || []).filter((segment) => segment.ok && segment.mp3);
  const targets = [];
  for (let index = 0; index < Math.min(sceneCount, segments.length); index += 1) {
    const duration = await probeDuration(segments[index].mp3);
    if (!duration) throw new Error(`Unable to probe voice segment ${segments[index].mp3}`);
    targets.push(duration + (index < segments.length - 1 ? silenceSec : 0));
  }
  return targets;
}

async function main() {
  const captureDir = path.resolve(arg('capture-dir', process.env.CAPTURE_DIR || process.cwd()));
  const voiceManifestPath = path.resolve(arg('voice-manifest', process.env.VOICEOVER_MANIFEST || ''));
  const audioPath = path.resolve(arg('audio', process.env.VOICEOVER_AUDIO || ''));
  const out = path.resolve(arg('out', process.env.OUTPUT_MP4 || path.join(captureDir, 'agentium-synced.mp4')));
  const width = Number(arg('width', process.env.OUTPUT_WIDTH || '2560'));
  const height = Number(arg('height', process.env.OUTPUT_HEIGHT || '1440'));
  const fps = Number(arg('fps', process.env.OUTPUT_FPS || '25'));
  const crf = String(arg('crf', process.env.OUTPUT_CRF || '19'));
  const preset = String(arg('preset', process.env.OUTPUT_PRESET || 'veryfast'));
  const holdLastScene = !hasFlag('speed-last-scene');

  if (!voiceManifestPath || voiceManifestPath === path.resolve('')) {
    throw new Error('--voice-manifest is required');
  }
  if (!audioPath || audioPath === path.resolve('')) {
    throw new Error('--audio is required');
  }

  const captureManifest = await readJson(path.join(captureDir, 'capture-manifest.json'));
  const voiceManifest = await readJson(voiceManifestPath);
  const video = path.resolve(captureManifest.continuousVideo || '');
  if (!video) throw new Error('capture manifest does not include continuousVideo');
  const scenes = safeSceneResults(captureManifest);
  if (!scenes.length) throw new Error('capture manifest does not include scene timings');

  const targets = await audioTargets(voiceManifest, scenes.length);
  if (targets.length !== scenes.length) {
    throw new Error(`Voice segment count (${targets.length}) does not match scene count (${scenes.length})`);
  }

  const firstStartedAt = Number(scenes[0].startedAtMs);
  const parts = [];
  const labels = [];
  const timeline = [];
  let finalDuration = 0;

  scenes.forEach((scene, index) => {
    const start = Math.max(0, (Number(scene.startedAtMs) - firstStartedAt) / 1000);
    const end = Math.max(start + 0.8, (Number(scene.endedAtMs) - firstStartedAt) / 1000);
    const rawDuration = end - start;
    const targetDuration = holdLastScene && index === scenes.length - 1 ? rawDuration : targets[index];
    const factor = targetDuration / rawDuration;
    const label = `[v${index}]`;
    parts.push(
      `[0:v]trim=start=${start.toFixed(3)}:end=${end.toFixed(3)},` +
        `setpts=(PTS-STARTPTS)*${factor.toFixed(6)},` +
        `scale=${width}:${height}:force_original_aspect_ratio=decrease,` +
        `pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2,` +
        `fps=${fps},format=yuv420p${label}`,
    );
    labels.push(label);
    timeline.push({
      id: scene.id,
      sourceStart: start,
      sourceEnd: end,
      rawDuration,
      targetDuration,
      speedFactor: rawDuration / targetDuration,
      outputStart: finalDuration,
      outputEnd: finalDuration + targetDuration,
    });
    finalDuration += targetDuration;
  });
  parts.push(`${labels.join('')}concat=n=${labels.length}:v=1:a=0[vout]`);

  await mkdir(path.dirname(out), { recursive: true });
  const args = [
    '-y',
    '-i',
    video,
    '-i',
    audioPath,
    '-filter_complex',
    parts.join(';'),
    '-map',
    '[vout]',
    '-map',
    '1:a:0',
    '-t',
    finalDuration.toFixed(3),
    '-c:v',
    'libx264',
    '-preset',
    preset,
    '-crf',
    crf,
    '-pix_fmt',
    'yuv420p',
    '-af',
    'apad',
    '-c:a',
    'aac',
    '-b:a',
    '192k',
    '-movflags',
    '+faststart',
    out,
  ];
  const ffmpeg = await run('ffmpeg', args);
  const outStat = await stat(out).catch(() => null);
  const report = {
    captureDir,
    video,
    audio: audioPath,
    out,
    width,
    height,
    fps,
    holdLastScene,
    finalDuration,
    timeline,
    ffmpeg: {
      ok: ffmpeg.ok,
      status: ffmpeg.status,
      stderrTail: ffmpeg.stderr.split('\n').slice(-40).join('\n'),
    },
    outputBytes: outStat?.size || 0,
  };
  const reportPath = path.join(path.dirname(out), 'sync-assemble-report.json');
  await writeFile(reportPath, JSON.stringify(report, null, 2));
  console.log(`${ffmpeg.ok && outStat ? 'OK' : 'FAIL'} synced ${scenes.length} scenes -> ${out}`);
  console.log(`Report: ${reportPath}`);
  process.exit(ffmpeg.ok && outStat ? 0 : 1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
