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

async function loadScenes(scenesPath) {
  if (!scenesPath) return [];
  return JSON.parse(await readFile(path.resolve(scenesPath), 'utf8'));
}

function actionMs(scene) {
  return (scene.actions || []).reduce((total, action) => total + Number(action.waitMs || 0), 0);
}

async function loadAssembleDurations(input) {
  const reportPath = path.join(path.dirname(input), 'assemble-report.json');
  const report = JSON.parse(await readFile(reportPath, 'utf8').catch(() => '{}'));
  const durations = Array.isArray(report.durations) ? report.durations.map(Number).filter((value) => Number.isFinite(value) && value > 0) : [];
  const transition = report.transition || null;
  const transitionDuration = transition ? Number(transition.duration || 0) : 0;
  return { durations, transitionDuration };
}

function sceneTimeline(scenes, duration, assembled = null) {
  const actualDurations = assembled?.durations || [];
  if (actualDurations.length === scenes.length) {
    const overlap = Number(assembled?.transitionDuration || 0);
    let cursor = 0;
    return scenes.map((scene, index) => {
      const sceneDuration = Math.max(1.2, actualDurations[index]);
      const start = Math.max(0, cursor);
      const end = Math.min(duration, start + sceneDuration);
      cursor = Math.max(start + 1.2, end - overlap);
      return {
        id: scene.id,
        title: scene.overlay?.title || scene.title || scene.id,
        kicker: scene.overlay?.kicker || scene.workspace || 'Agentium',
        overlay: scene.overlay || {},
        start,
        end,
      };
    });
  }

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
      overlay: scene.overlay || {},
      start,
      end,
    };
  });
}

async function generateOverlayPngs({ timeline, outDir, width, height, logo }) {
  const overlayDir = path.join(outDir, '.polish-overlays');
  await mkdir(overlayDir, { recursive: true });
  const payloadPath = path.join(overlayDir, 'timeline.json');
  const scriptPath = path.join(overlayDir, 'render_overlays.py');
  await writeFile(payloadPath, JSON.stringify({ timeline, width, height, logo }, null, 2));
  await writeFile(scriptPath, String.raw`
import json
import os
import textwrap
from PIL import Image, ImageDraw, ImageFont

payload_path = r"${payloadPath}"
out_dir = r"${overlayDir}"

with open(payload_path, "r", encoding="utf-8") as fh:
    payload = json.load(fh)

W = int(payload["width"])
H = int(payload["height"])
logo_path = payload.get("logo")

def font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                pass
    return ImageFont.load_default()

small = font(20)
small_bold = font(22, True)
title_font = font(36, True)
brand_font = font(22, True)
tag_font = font(18)
chip_font = font(17, True)
metric_font = font(24, True)
metric_small = font(15, True)

def text_size(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]

def shadow_text(draw, xy, text, font, fill, shadow=(0, 0, 0, 210), offset=(2, 2)):
    x, y = xy
    draw.text((x + offset[0], y + offset[1]), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)

def pill(draw, xy, text, font, fill, outline, text_fill, pad_x=16, pad_y=8):
    x, y = xy
    tw, th = text_size(draw, text, font)
    box = (x, y, x + tw + pad_x * 2, y + th + pad_y * 2)
    draw.rounded_rectangle(box, radius=14, fill=fill, outline=outline, width=1)
    draw.text((x + pad_x, y + pad_y - 1), text, font=font, fill=text_fill)
    return box[2] + 8

logo_img = None
if logo_path and os.path.exists(logo_path):
    logo_img = Image.open(logo_path).convert("RGBA")
    logo_img.thumbnail((150, 64), Image.Resampling.LANCZOS)
    alpha = logo_img.getchannel("A").point(lambda p: int(p * 0.78))
    logo_img.putalpha(alpha)

for index, item in enumerate(payload["timeline"]):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    overlay = item.get("overlay") or {}
    cyan = (103, 232, 249, 225)
    white = (248, 250, 252, 242)
    muted = (178, 190, 205, 220)
    panel = (2, 7, 13, 202)
    stroke = (34, 211, 238, 128)
    green = (52, 211, 153, 225)
    amber = (251, 191, 36, 225)
    purple = (196, 181, 253, 225)

    right_text = "AI OPERATING SYSTEM 2026"
    rb = draw.textbbox((0, 0), right_text, font=tag_font)
    shadow_text(draw, (W - (rb[2] - rb[0]) - 64, 50), right_text, font=tag_font, fill=cyan)
    draw.rectangle((0, H - 4, W, H), fill=(34, 211, 238, 184))

    active_stage = str(overlay.get("stage") or "BUILD").upper()

    metric = overlay.get("metric") or {}
    if metric:
        mx, my, mw, mh = W - 456, 94, 392, 88
        draw.rounded_rectangle((mx, my, mx + mw, my + mh), radius=12, fill=(2, 7, 13, 190), outline=(52, 211, 153, 118), width=1)
        label = str(metric.get("label") or "EXECUTIVE SIGNAL").upper()
        value = str(metric.get("value") or "")
        shadow_text(draw, (mx + 20, my + 15), label, font=metric_small, fill=green)
        shadow_text(draw, (mx + 20, my + 40), value, font=metric_font, fill=white)
        trend = str(metric.get("trend") or "")
        if trend:
            tbw, _ = text_size(draw, trend, metric_small)
            draw.rounded_rectangle((mx + mw - tbw - 42, my + 32, mx + mw - 18, my + 63), radius=11, fill=(52, 211, 153, 42), outline=(52, 211, 153, 112), width=1)
            draw.text((mx + mw - tbw - 30, my + 39), trend, font=metric_small, fill=green)

    x, y, w, h = 56, H - 238, 820, 124
    draw.rounded_rectangle((x, y, x + w, y + h), radius=10, fill=panel, outline=stroke, width=1)
    draw.rectangle((x, y, x + 5, y + h), fill=cyan)
    kicker = str(item.get("kicker") or "Agentium").upper()
    title = str(item.get("title") or item.get("id") or "")
    stage_end = pill(draw, (x + 32, y + 20), active_stage, metric_small, (34, 211, 238, 190), (103, 232, 249, 230), (2, 7, 13, 245), pad_x=12, pad_y=7)
    shadow_text(draw, (stage_end + 8, y + 25), kicker, font=small_bold, fill=cyan)
    wrapped = textwrap.wrap(title, width=38)[:2]
    for line_idx, line in enumerate(wrapped):
        shadow_text(draw, (x + 32, y + 61 + line_idx * 38), line, font=title_font, fill=white)

    scene_no = f"{index + 1:02d}/{len(payload['timeline']):02d}"
    shadow_text(draw, (x + w - 82, y + 28), scene_no, font=small, fill=muted)

    chips = [str(chip) for chip in (overlay.get("chips") or [])][:4]
    if chips:
        cx, cy = x + w + 26, y + 18
        draw.rounded_rectangle((cx - 12, cy - 12, min(W - 250, cx + 650), cy + 92), radius=10, fill=(2, 7, 13, 150), outline=(148, 163, 184, 58), width=1)
        chip_colors = [cyan, green, amber, purple]
        for chip_idx, chip in enumerate(chips):
            cx = pill(draw, (cx, cy + (chip_idx // 2) * 42), chip.upper(), chip_font, (15, 23, 34, 206), (34, 211, 238, 92), chip_colors[chip_idx % len(chip_colors)], pad_x=14, pad_y=8)
            if chip_idx == 1:
                cx = x + w + 26
    if logo_img is not None:
        lx, ly = W - logo_img.width - 64, H - logo_img.height - 44
        draw.rounded_rectangle((lx - 14, ly - 10, lx + logo_img.width + 14, ly + logo_img.height + 10), radius=10, fill=(0, 0, 0, 118), outline=(34, 211, 238, 52), width=1)
        img.alpha_composite(logo_img, (lx, ly))
    out = os.path.join(out_dir, f"overlay-{index:02d}.png")
    img.save(out)
`);
  const rendered = await run('python', [scriptPath]);
  if (!rendered.ok) {
    throw new Error(`Overlay generation failed: ${rendered.stderr || rendered.stdout}`);
  }
  return timeline.map((_, index) => path.join(overlayDir, `overlay-${String(index).padStart(2, '0')}.png`));
}

async function main() {
  const input = path.resolve(arg('input', process.env.INPUT_MP4 || ''));
  if (!input) throw new Error('--input=/path/to/video.mp4 is required');
  const out = path.resolve(arg('out', process.env.OUTPUT_MP4 || input.replace(/\.mp4$/i, '-polished.mp4')));
  const width = Number(arg('width', process.env.OUTPUT_WIDTH || '1920'));
  const height = Number(arg('height', process.env.OUTPUT_HEIGHT || '1080'));
  const logo = path.resolve(arg('logo', process.env.DATATEGY_LOGO || path.join(__dirname, 'assets/datategy-logo.png')));
  const scenesPath = arg('scenes', process.env.SCENES_FILE || path.join(__dirname, 'agentium_video_scenes.json'));
  const overlayStyle = String(arg('overlay-style', process.env.OVERLAY_STYLE || 'classic')).toLowerCase();
  const duration = await probeDuration(input);
  if (!duration) throw new Error(`Unable to probe duration for ${input}`);
  const scenes = await loadScenes(scenesPath);
  const assembled = await loadAssembleDurations(input);
  const timeline = sceneTimeline(scenes, duration, assembled);
  await mkdir(path.dirname(out), { recursive: true });

  const hasLogo = Boolean(await stat(logo).catch(() => null));
  const overlayFiles = overlayStyle === 'none'
    ? []
    : await generateOverlayPngs({
        timeline,
        outDir: path.dirname(out),
        width,
        height,
        logo: hasLogo ? logo : null,
      });
  const args = ['-y', '-i', input];
  for (const file of overlayFiles) args.push('-i', file);

  const baseFilters = [
    `scale=${width}:${height}:force_original_aspect_ratio=decrease`,
    `pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2`,
    'fps=25',
    'format=rgba',
    'eq=contrast=1.045:saturation=1.08:brightness=0.006',
    'unsharp=5:5:0.45:3:3:0.18',
    'vignette=PI/5:mode=backward',
  ];

  const parts = [`[0:v]${baseFilters.join(',')}[v0]`];
  if (overlayFiles.length > 0) {
    for (let index = 0; index < overlayFiles.length; index += 1) {
      const item = timeline[index];
      const start = Math.min(item.end, item.start + 0.35).toFixed(2);
      const end = Math.min(item.end - 0.15, item.start + 4.7).toFixed(2);
      if (Number(end) <= Number(start)) continue;
      const inputLabel = `[${index + 1}:v]`;
      const previous = `[v${index}]`;
      const next = index === overlayFiles.length - 1 ? '[vout]' : `[v${index + 1}]`;
      parts.push(`${previous}${inputLabel}overlay=x=0:y=0:enable='between(t\\,${start}\\,${end})'${next}`);
    }
  } else {
    parts.push('[v0]null[vout]');
  }
  args.push('-filter_complex', parts.join(';'), '-map', '[vout]', '-map', '0:a?');
  args.push('-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', out);

  const result = await run('ffmpeg', args);
  const outStat = await stat(out).catch(() => null);
  const report = {
    input,
    out,
    logo: hasLogo ? logo : null,
    scenesPath,
    overlayStyle,
    duration,
    timeline,
    overlayFiles,
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
