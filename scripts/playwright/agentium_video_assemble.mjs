#!/usr/bin/env node
import { mkdir, readdir, readFile, stat, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import path from 'node:path';

function arg(name, fallback = null) {
  const prefix = `--${name}=`;
  const found = process.argv.find((item) => item.startsWith(prefix));
  if (found) return found.slice(prefix.length);
  return fallback;
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
  if (!result.ok) return null;
  const value = Number(result.stdout.trim());
  return Number.isFinite(value) && value > 0 ? value : null;
}

async function listWebm(dir) {
  const manifestPath = path.join(dir, 'capture-manifest.json');
  try {
    const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
    if (manifest.continuousVideo) return [manifest.continuousVideo];
    const fromManifest = (manifest.results || [])
      .map((item) => item.video)
      .filter(Boolean);
    if (fromManifest.length > 0) return [...new Set(fromManifest)];
  } catch {}

  const videoDir = path.join(dir, 'video');
  const qualificationVideo = path.join(videoDir, 'qualification.webm');
  if (await stat(qualificationVideo).catch(() => null)) {
    return [qualificationVideo];
  }
  const entries = await readdir(videoDir);
  return entries
    .filter((name) => name.endsWith('.webm'))
    .sort()
    .map((name) => path.join(videoDir, name));
}

async function loadCaptureDurations(dir, trimStart = 0) {
  const manifestPath = path.join(dir, 'capture-manifest.json');
  try {
    const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
    const durations = (manifest.results || [])
      .filter((item) => item.id !== 'continuous-video-save')
      .map((item) => {
        const start = Number(item.startedAtMs || 0);
        const end = Number(item.endedAtMs || 0);
        return start > 0 && end > start ? (end - start) / 1000 : null;
      })
      .filter((value) => Number.isFinite(value) && value > 0);
    if (durations.length > 0 && trimStart > 0) {
      durations[0] = Math.max(1.2, durations[0] - trimStart);
    }
    return durations;
  } catch {
    return [];
  }
}

function escapeConcatPath(file) {
  return file.replace(/'/g, "'\\''");
}

async function concatArgs({ dir, videos, audio, out, trimStart }) {
  const concatFile = path.join(dir, 'ffmpeg-concat-list.txt');
  await writeFile(concatFile, videos.map((file) => `file '${escapeConcatPath(path.resolve(file))}'`).join('\n') + '\n');
  const args = [
    '-y',
    '-f',
    'concat',
    '-safe',
    '0',
    '-i',
    concatFile,
  ];
  if (audio) {
    args.push('-i', path.resolve(audio), '-map', '0:v:0', '-map', '1:a:0', '-shortest');
  }
  if (trimStart > 0) {
    args.push('-vf', `trim=start=${trimStart},setpts=PTS-STARTPTS`);
  }
  args.push(
    '-c:v',
    'libx264',
    '-preset',
    'veryfast',
    '-crf',
    '20',
    '-pix_fmt',
    'yuv420p',
  );
  if (audio) {
    args.push('-af', 'apad', '-c:a', 'aac', '-b:a', '160k');
  } else {
    args.push('-an');
  }
  args.push('-movflags', '+faststart', out);
  return { args, concatFile, filterGraph: null };
}

async function transitionArgs({ videos, audio, out, transition, transitionDuration, width, height, trimStart }) {
  const durations = [];
  for (const video of videos) {
    const duration = await probeDuration(video);
    if (!duration) {
      throw new Error(`Unable to probe duration for ${video}`);
    }
    durations.push(Math.max(1.2, duration - trimStart));
  }

  const args = ['-y'];
  for (const video of videos) args.push('-i', path.resolve(video));
  if (audio) args.push('-i', path.resolve(audio));

  const parts = [];
  for (let idx = 0; idx < videos.length; idx += 1) {
    parts.push(
      `[${idx}:v]scale=${width}:${height}:force_original_aspect_ratio=decrease,` +
        `pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2,` +
        `fps=25,format=yuv420p,trim=start=${trimStart},settb=AVTB,setpts=PTS-STARTPTS` +
        `[v${idx}]`,
    );
  }

  let currentLabel = '[v0]';
  let elapsed = durations[0];
  for (let idx = 1; idx < videos.length; idx += 1) {
    const outLabel = idx === videos.length - 1 ? '[vout]' : `[vx${idx}]`;
    const offset = Math.max(0, elapsed - transitionDuration);
    parts.push(
      `${currentLabel}[v${idx}]xfade=transition=${transition}:duration=${transitionDuration}:offset=${offset.toFixed(3)}${outLabel}`,
    );
    elapsed = elapsed + durations[idx] - transitionDuration;
    currentLabel = outLabel;
  }

  args.push('-filter_complex', parts.join(';'), '-map', '[vout]');
  if (audio) {
    const audioIndex = videos.length;
    args.push('-map', `${audioIndex}:a:0`, '-shortest');
  }
  args.push(
    '-c:v',
    'libx264',
    '-preset',
    'veryfast',
    '-crf',
    '20',
    '-pix_fmt',
    'yuv420p',
  );
  if (audio) {
    args.push('-af', 'apad', '-c:a', 'aac', '-b:a', '160k');
  } else {
    args.push('-an');
  }
  args.push('-movflags', '+faststart', out);
  return { args, concatFile: null, filterGraph: parts.join(';'), durations };
}

async function main() {
  const dir = path.resolve(arg('dir', process.env.CAPTURE_DIR || process.cwd()));
  const out = path.resolve(arg('out', process.env.OUTPUT_MP4 || path.join(dir, 'agentium-capture.mp4')));
  const audio = arg('audio', process.env.VOICEOVER_AUDIO || null);
  const transition = arg('transition', process.env.VIDEO_TRANSITION || 'none');
  const transitionDuration = Number(arg('transition-duration', process.env.VIDEO_TRANSITION_DURATION || '0.55'));
  const trimStart = Number(arg('trim-start', process.env.VIDEO_TRIM_START || '0'));
  const width = Number(arg('width', process.env.OUTPUT_WIDTH || '1920'));
  const height = Number(arg('height', process.env.OUTPUT_HEIGHT || '1080'));
  const videos = await listWebm(dir);
  const captureDurations = await loadCaptureDurations(dir, trimStart);
  if (videos.length === 0) {
    throw new Error(`No .webm files found under ${dir}`);
  }
  await mkdir(path.dirname(out), { recursive: true });
  const useTransitions = transition !== 'none' && videos.length > 1;
  const plan = useTransitions
    ? await transitionArgs({
        videos,
        audio,
        out,
        transition,
        transitionDuration,
        width,
        height,
        trimStart,
      })
    : await concatArgs({ dir, videos, audio, out, trimStart });

  const result = await run('ffmpeg', plan.args);
  const outStat = await stat(out).catch(() => null);
  const report = {
    dir,
    out,
    audio,
    videos,
    transition: useTransitions ? { name: transition, duration: transitionDuration, width, height } : null,
    trimStart,
    concatFile: plan.concatFile,
    filterGraph: plan.filterGraph,
    durations: plan.durations || captureDurations,
    ffmpeg: {
      ok: result.ok,
      status: result.status,
      stderrTail: result.stderr.split('\n').slice(-30).join('\n'),
    },
    outputBytes: outStat?.size || 0,
  };
  const reportPath = path.join(path.dirname(out), 'assemble-report.json');
  await writeFile(reportPath, JSON.stringify(report, null, 2));
  console.log(`${result.ok && outStat ? 'OK' : 'FAIL'} assembled ${videos.length} video(s) -> ${out}`);
  console.log(`Report: ${reportPath}`);
  process.exit(result.ok && outStat ? 0 : 1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
