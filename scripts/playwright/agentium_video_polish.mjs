#!/usr/bin/env node
import { readFile, stat, writeFile, mkdir } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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
  const value = Number(result.stdout.trim());
  return result.ok && Number.isFinite(value) && value > 0 ? value : null;
}

function ffText(value) {
  return String(value || '')
    .replace(/\\/g, '\\\\')
    .replace(/:/g, '\\:')
    .replace(/'/g, "\\'")
    .replace(/\[/g, '\\[')
    .replace(/\]/g, '\\]');
}

async function loadScenes(scenesPath) {
  if (!scenesPath) return [];
  return JSON.parse(await readFile(path.resolve(scenesPath), 'utf8'));
}

function actionMs(scene) {
  return (scene.actions || []).reduce((total, action) => total + Number(action.waitMs || 0), 0);
}

function sceneTimeline(scenes, duration) {
  const weights = scenes.map((scene) => Math.max(2500, Number(scene.waitMs || 4000) + actionMs(scene)));
  const total = weights.reduce((sum, weight) => sum + weight, 0) || 1;
  let cursor = 0;
  return scenes.map((scene, index) => {
    const seconds = (weights[index] / total) * duration;
    const start = cursor;
    const end = Math.min(duration, start + Math.max(2.5, seconds));
    cursor = end;
    return {
      id: scene.id,
      title: scene.overlay?.title || scene.title || scene.id,
      kicker: scene.overlay?.kicker || scene.workspace || 'Agentium',
      start,
      end,
    };
  });
}

function titleFilters(timeline) {
  const filters = [];
  for (const item of timeline) {
    const start = item.start.toFixed(2);
    const end = Math.min(item.end, item.start + 4.2).toFixed(2);
    const enable = `between(t\\,${start}\\,${end})`;
    filters.push(
      `drawbox=x=56:y=840:w=720:h=112:color=0x02070dcc@0.58:t=fill:enable='${enable}'`,
      `drawtext=text='${ffText(item.kicker)}':x=88:y=866:fontsize=21:fontcolor=0x67e8f9:letter_spacing=4:enable='${enable}'`,
      `drawtext=text='${ffText(item.title)}':x=88:y=898:fontsize=38:fontcolor=white:enable='${enable}'`,
    );
  }
  return filters;
}

async function main() {
  const input = path.resolve(arg('input', process.env.INPUT_MP4 || ''));
  if (!input) throw new Error('--input=/path/to/video.mp4 is required');
  const out = path.resolve(arg('out', process.env.OUTPUT_MP4 || input.replace(/\.mp4$/i, '-polished.mp4')));
  const width = Number(arg('width', process.env.OUTPUT_WIDTH || '1920'));
  const height = Number(arg('height', process.env.OUTPUT_HEIGHT || '1080'));
  const logo = path.resolve(arg('logo', process.env.DATATEGY_LOGO || path.join(__dirname, 'assets/datategy-logo.png')));
  const scenesPath = arg('scenes', process.env.SCENES_FILE || path.join(__dirname, 'agentium_video_scenes.json'));
  const duration = await probeDuration(input);
  if (!duration) throw new Error(`Unable to probe duration for ${input}`);
  const scenes = await loadScenes(scenesPath);
  const timeline = sceneTimeline(scenes, duration);
  await mkdir(path.dirname(out), { recursive: true });

  const hasLogo = Boolean(await stat(logo).catch(() => null));
  const args = ['-y', '-i', input];
  if (hasLogo) args.push('-i', logo);

  const baseFilters = [
    `scale=${width}:${height}:force_original_aspect_ratio=decrease`,
    `pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2`,
    'fps=25',
    'format=rgba',
    'eq=contrast=1.045:saturation=1.08:brightness=0.006',
    'unsharp=5:5:0.45:3:3:0.18',
    'vignette=PI/5:mode=backward',
    "drawtext=text='DATATEGY  //  AGENTIUM':x=64:y=48:fontsize=24:fontcolor=white@0.88:letter_spacing=5",
    "drawtext=text='AI OPERATING SYSTEM 2026':x=w-tw-64:y=50:fontsize=20:fontcolor=0x67e8f9@0.88:letter_spacing=4",
    "drawbox=x=0:y=h-3:w=w:h=3:color=0x22d3ee@0.72:t=fill",
    ...titleFilters(timeline),
  ];

  if (hasLogo) {
    args.push(
      '-filter_complex',
      `[1:v]scale=138:-1,format=rgba,colorchannelmixer=aa=0.72[logo];[0:v]${baseFilters.join(',')}[base];[base][logo]overlay=x=w-overlay_w-64:y=h-overlay_h-48[vout]`,
      '-map',
      '[vout]',
      '-map',
      '0:a?',
    );
  } else {
    args.push('-vf', baseFilters.join(','), '-map', '0:v:0', '-map', '0:a?');
  }
  args.push('-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', out);

  const result = await run('ffmpeg', args);
  const outStat = await stat(out).catch(() => null);
  const report = {
    input,
    out,
    logo: hasLogo ? logo : null,
    scenesPath,
    duration,
    timeline,
    ffmpeg: {
      ok: result.ok,
      status: result.status,
      stderrTail: result.stderr.split('\n').slice(-40).join('\n'),
    },
    outputBytes: outStat?.size || 0,
  };
  const reportPath = path.join(path.dirname(out), 'polish-report.json');
  await writeFile(reportPath, JSON.stringify(report, null, 2));
  console.log(`${result.ok && outStat ? 'OK' : 'FAIL'} polished -> ${out}`);
  console.log(`Report: ${reportPath}`);
  process.exit(result.ok && outStat ? 0 : 1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
