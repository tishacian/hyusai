#!/usr/bin/env node
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(__dirname, '../..');

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
  args.push('-filter_complex', filterParts.join(';'));
  args.push('-map', '[out]', '-c:a', 'pcm_s16le', output);
  const ffmpeg = await run('ffmpeg', args);
  return { output, ffmpeg, ok: ffmpeg.ok };
}

async function main() {
  const scriptPath = path.resolve(arg('script', process.env.VOICEOVER_SCRIPT || path.join(__dirname, 'agentium_voiceover_script.json')));
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const outDir = path.resolve(arg('out-dir', process.env.OUT_DIR || path.join(repo, 'docs/video-captures', `voiceover-${stamp}`)));
  const voice = arg('voice', process.env.VOICEOVER_VOICE || '');
  const rate = arg('rate', process.env.VOICEOVER_RATE || '175');
  const silenceSec = Number(arg('silence', process.env.VOICEOVER_SILENCE_SEC || '0.75'));
  await mkdir(outDir, { recursive: true });

  const segments = JSON.parse(await readFile(scriptPath, 'utf8'));
  const manifest = {
    startedAt: new Date().toISOString(),
    scriptPath,
    outDir,
    voice: voice || '(system default)',
    rate,
    silenceSec,
    segments: [],
  };

  for (const segment of segments) {
    const id = String(segment.id || `segment-${manifest.segments.length + 1}`).replace(/[^a-zA-Z0-9._-]/g, '-');
    const aiff = path.join(outDir, `${id}.aiff`);
    const wav = path.join(outDir, `${id}.wav`);
    const sayArgs = [];
    if (voice) sayArgs.push('-v', voice);
    sayArgs.push('-r', rate, '-o', aiff, segment.text || '');
    const say = await run('say', sayArgs);
    const entry = { id, text: segment.text || '', aiff, wav, say };
    if (say.ok) {
      const convert = await run('afconvert', ['-f', 'WAVE', '-d', 'LEI16', aiff, wav]);
      entry.afconvert = convert;
      entry.ok = convert.ok || say.ok;
      if (!convert.ok) entry.warning = 'AIFF generated, WAV conversion failed';
    } else {
      entry.ok = false;
    }
    manifest.segments.push(entry);
    console.log(`${entry.ok ? 'OK' : 'FAIL'} ${id}`);
  }

  const segmentFiles = manifest.segments
    .filter((segment) => segment.ok && segment.wav)
    .map((segment) => segment.wav);
  manifest.combined = await buildCombinedVoiceover(outDir, segmentFiles, silenceSec);

  const manifestPath = path.join(outDir, 'voiceover-manifest.json');
  await writeFile(manifestPath, JSON.stringify(manifest, null, 2));
  const failed = manifest.segments.filter((segment) => !segment.ok).length;
  console.log(`Voiceover complete: ${manifest.segments.length - failed} ok / ${failed} failed`);
  console.log(`Manifest: ${manifestPath}`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
