#!/usr/bin/env node
import {copyFile, readFile, stat, writeFile, mkdir} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function arg(name, fallback = null) {
  const prefix = `--${name}=`;
  const found = process.argv.find((item) => item.startsWith(prefix));
  if (found) return found.slice(prefix.length);
  return fallback;
}

function run(command, args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {stdio: ['ignore', 'pipe', 'pipe'], ...options});
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
      process.stdout.write(chunk);
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
      process.stderr.write(chunk);
    });
    child.on('close', (status) => resolve({status, stdout, stderr, ok: status === 0}));
  });
}

async function readJson(file) {
  return JSON.parse(await readFile(path.resolve(file), 'utf8'));
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
  ], {stdio: ['ignore', 'pipe', 'pipe']});
  const value = Number(result.stdout.trim());
  return result.ok && Number.isFinite(value) && value > 0 ? value : null;
}

function sceneById(scenes) {
  const map = new Map();
  for (const scene of scenes) {
    map.set(scene.id, scene);
  }
  return map;
}

async function main() {
  const input = path.resolve(arg('input', process.env.AGENTIUM_REMOTION_INPUT || ''));
  const out = path.resolve(arg('out', process.env.AGENTIUM_REMOTION_OUT || path.join(path.dirname(input), 'agentium-remotion-final.mp4')));
  const timelinePath = path.resolve(arg('timeline', process.env.AGENTIUM_SYNC_REPORT || path.join(path.dirname(input), 'sync-assemble-report.json')));
  const scenesPath = path.resolve(arg('scenes', process.env.AGENTIUM_SCENES || path.join(__dirname, 'agentium_video_scenes.json')));
  const browserExecutable = arg(
    'browser-executable',
    process.env.REMOTION_BROWSER_EXECUTABLE ||
      '/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell',
  );
  const width = Number(arg('width', process.env.OUTPUT_WIDTH || '2560'));
  const height = Number(arg('height', process.env.OUTPUT_HEIGHT || '1440'));
  const fps = Number(arg('fps', process.env.OUTPUT_FPS || '25'));
  const crf = String(arg('crf', process.env.REMOTION_CRF || '16'));
  const concurrency = String(arg('concurrency', process.env.REMOTION_CONCURRENCY || '4'));
  if (!input || input === path.resolve('')) throw new Error('--input is required');

  const syncReport = await readJson(timelinePath);
  const scenesConfig = await readJson(scenesPath);
  const sceneConfigMap = sceneById(scenesConfig);
  const durationSec = Number(syncReport.finalDuration || (await probeDuration(input)) || 0);
  if (!durationSec) throw new Error(`Unable to determine duration for ${input}`);

  const scenes = (syncReport.timeline || []).map((item) => {
    const config = sceneConfigMap.get(item.id) || {};
    return {
      id: item.id,
      start: Number(item.outputStart || 0),
      end: Number(item.outputEnd || 0),
      stage: config.overlay?.stage || '',
      title: config.overlay?.title || config.title || item.id,
      kicker: config.overlay?.kicker || config.workspace || 'Agentium',
    };
  });

  await mkdir(path.dirname(out), {recursive: true});
  const publicGeneratedDir = path.join(__dirname, 'remotion', 'public', 'generated');
  await mkdir(publicGeneratedDir, {recursive: true});
  const publicInput = path.join(publicGeneratedDir, 'agentium-input.mp4');
  await copyFile(input, publicInput);
  const propsPath = path.join(path.dirname(out), 'remotion-props.json');
  const props = {
    videoSrc: 'static:generated/agentium-input.mp4',
    durationSec,
    fps,
    width,
    height,
    scenes,
  };
  await writeFile(propsPath, JSON.stringify(props, null, 2));

  const entry = path.join(__dirname, 'remotion', 'index.tsx');
  const publicDir = path.join(__dirname, 'remotion', 'public');
  const args = [
    'remotion',
    'render',
    entry,
    'AgentiumDemo',
    out,
    `--props=${propsPath}`,
    `--public-dir=${publicDir}`,
    `--browser-executable=${browserExecutable}`,
    `--width=${width}`,
    `--height=${height}`,
    `--fps=${fps}`,
    `--duration=${Math.ceil(durationSec * fps)}`,
    '--codec=h264',
    '--audio-codec=aac',
    `--crf=${crf}`,
    '--x264-preset=medium',
    `--concurrency=${concurrency}`,
    '--overwrite',
  ];
  const result = await run('npx', args, {cwd: __dirname});
  const outStat = await stat(out).catch(() => null);
  const report = {
    input,
    out,
    propsPath,
    timelinePath,
    scenesPath,
    durationSec,
    browserExecutable,
    ffmpeg: {
      ok: result.ok,
      status: result.status,
      stderrTail: result.stderr.split('\n').slice(-40).join('\n'),
    },
    outputBytes: outStat?.size || 0,
  };
  const reportPath = path.join(path.dirname(out), 'remotion-render-report.json');
  await writeFile(reportPath, JSON.stringify(report, null, 2));
  console.log(`${result.ok && outStat ? 'OK' : 'FAIL'} remotion render -> ${out}`);
  console.log(`Report: ${reportPath}`);
  process.exit(result.ok && outStat ? 0 : 1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
