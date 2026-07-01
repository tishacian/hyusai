#!/usr/bin/env node
import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
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

function hasFlag(name) {
  return process.argv.includes(`--${name}`);
}

function viewportFromArgs() {
  const preset = String(arg('preset', process.env.CAPTURE_PRESET || '1080p')).toLowerCase();
  const presets = {
    '900p': { width: 1600, height: 900 },
    '1080p': { width: 1920, height: 1080 },
    fhd: { width: 1920, height: 1080 },
    '1440p': { width: 2560, height: 1440 },
    qhd: { width: 2560, height: 1440 },
    '2160p': { width: 3840, height: 2160 },
    '4k': { width: 3840, height: 2160 },
  };
  const selected = presets[preset] || presets['1080p'];
  return {
    preset,
    width: Number(arg('width', process.env.CAPTURE_WIDTH || String(selected.width))),
    height: Number(arg('height', process.env.CAPTURE_HEIGHT || String(selected.height))),
  };
}

function tool(name, args = ['--version']) {
  const res = spawnSync(name, args, { encoding: 'utf8' });
  return {
    ok: res.status === 0,
    status: res.status,
    stdout: (res.stdout || '').split('\n').slice(0, 2).join('\n'),
    stderr: (res.stderr || '').split('\n').slice(0, 2).join('\n'),
  };
}

async function main() {
  const host = (arg('host', process.env.AGENTIUM_HOST || 'https://agentium.papai.ai') || '').replace(/\/+$/, '');
  const email = arg('email', process.env.AGENTIUM_EMAIL || 'thibaud.ishacian@datategy.net');
  const password = process.env.AGENTIUM_PASSWORD || '';
  const skipLogin = hasFlag('no-login') || !password;
  const viewport = viewportFromArgs();
  const deviceScaleFactor = Number(arg('scale', process.env.CAPTURE_DEVICE_SCALE_FACTOR || '1'));
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const outDir = path.resolve(arg('out-dir', process.env.OUT_DIR || path.join(repo, 'docs/video-captures', `qualification-${stamp}`)));
  const videoDir = path.join(outDir, 'video');
  const screenshotDir = path.join(outDir, 'screenshots');
  await mkdir(videoDir, { recursive: true });
  await mkdir(screenshotDir, { recursive: true });

  const report = {
    startedAt: new Date().toISOString(),
    host,
    email,
    outDir,
    viewport: { ...viewport, deviceScaleFactor },
    tools: {
      node: { ok: true, version: process.version },
      ffmpeg: tool('ffmpeg', ['-version']),
      say: tool('say', ['-v', '?']),
      afconvert: (() => {
        const probe = tool('afconvert', ['-h']);
        return {
          ...probe,
          ok: probe.ok || /Audio File Convert/i.test(`${probe.stdout}\n${probe.stderr}`),
        };
      })(),
    },
    checks: [],
  };

  const browser = await chromium.launch({ headless: !hasFlag('headed') });
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor,
    ignoreHTTPSErrors: true,
    recordVideo: { dir: videoDir, size: { width: viewport.width, height: viewport.height } },
  });
  const page = await context.newPage();
  let video = null;
  try {
    video = page.video();
    await page.goto(`${host}/auth/signin`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await page.waitForTimeout(2500);
    const screenshot = path.join(screenshotDir, 'signin.png');
    await page.screenshot({ path: screenshot, fullPage: false });
    const signinText = await page.locator('body').innerText({ timeout: 10_000 }).catch(() => '');
    report.checks.push({
      name: 'signin_page',
      ok: /sign|email|connexion|login/i.test(signinText),
      url: page.url(),
      screenshot,
    });

    if (!skipLogin) {
      const login = await page.evaluate(
        async ({ userEmail, userPassword }) => {
          const res = await fetch('/api/v1/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: userEmail, password: userPassword, remember_me: false }),
          });
          const body = await res.json().catch(() => ({}));
          if (!res.ok || !body.token) return { ok: false, status: res.status, body };
          localStorage.setItem('agentium_token', `Bearer ${body.token}`);
          if (body.refresh_token) localStorage.setItem('agentium_refresh_token', body.refresh_token);
          return { ok: true, status: res.status, workspace_slug: body.workspace_slug, workspace_count: Array.isArray(body.workspaces) ? body.workspaces.length : null };
        },
        { userEmail: email, userPassword: password },
      );
      report.checks.push({ name: 'api_login', ...login });
      if (login.ok) {
        await page.goto(`${host}/hypervisor`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
        await page.waitForTimeout(3500);
        const shot = path.join(screenshotDir, 'hypervisor-after-login.png');
        await page.screenshot({ path: shot, fullPage: false });
        report.checks.push({ name: 'hypervisor_after_login', ok: !/sign in|connexion/i.test(await page.locator('body').innerText().catch(() => '')), url: page.url(), screenshot: shot });
      }
    } else {
      report.checks.push({ name: 'api_login', ok: false, skipped: true, reason: 'AGENTIUM_PASSWORD not set or --no-login used' });
    }
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
    if (video) {
      const saved = path.join(videoDir, 'qualification.webm');
      await video.saveAs(saved).catch((err) => {
        report.checks.push({ name: 'video_save', ok: false, error: err.message });
      });
      await video.delete().catch(() => {});
      report.checks.push({ name: 'video_recording', ok: true, file: saved });
    }
    await browser.close();
  }

  const reportPath = path.join(outDir, 'qualification-report.json');
  await writeFile(reportPath, JSON.stringify(report, null, 2));

  const okCount = report.checks.filter((item) => item.ok).length;
  const failed = report.checks.filter((item) => item.ok === false && !item.skipped).length;
  const skipped = report.checks.filter((item) => item.skipped).length;
  console.log(`Agentium capture qualification: ${okCount} ok / ${failed} failed / ${skipped} skipped`);
  console.log(`Report: ${reportPath}`);
  if (!report.tools.ffmpeg.ok) {
    console.log('WARN ffmpeg missing: capture works, final mp4 assembly will be unavailable until ffmpeg is installed.');
  }
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
