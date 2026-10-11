#!/usr/bin/env node
/**
 * Speak into the WE assistant and watch the composer fill up, using a WAV file
 * as the microphone so the words are real speech rather than Chrome's test tone.
 * Run from frontend-ng:
 *   E2E_USERNAME=... E2E_PASSWORD=... node e2e/probe-nawa-dictation.mjs
 *
 * Make the speech with any voice, for instance the platform's own synthesis:
 *   ffmpeg -i said.mp3 -ar 48000 -ac 1 /tmp/say.wav
 *
 * Proves two things no unit test reaches: the text grows while the recording
 * runs, and reaching for the keyboard keeps the sentence instead of sending it.
 */
import { chromium } from 'playwright';

const BASE = process.env.E2E_BASE_URL ?? 'https://agentium.papai.ai';
const USER = process.env.E2E_USERNAME;
const PASS = process.env.E2E_PASSWORD;
const SPEECH = process.env.E2E_SPEECH_WAV ?? '/tmp/say.wav';
const EXECUTABLE =
  process.env.E2E_CHROMIUM_EXECUTABLE ??
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

if (!USER || !PASS) {
  console.error('Set E2E_USERNAME and E2E_PASSWORD');
  process.exit(1);
}

const browser = await chromium.launch({
  executablePath: EXECUTABLE,
  args: [
    '--use-fake-ui-for-media-stream',
    '--use-fake-device-for-media-stream',
    `--use-file-for-fake-audio-capture=${SPEECH}%noloop`,
  ],
});
const context = await browser.newContext({
  viewport: { width: 1280, height: 860 },
  deviceScaleFactor: 2,
  permissions: ['microphone'],
});
const page = await context.newPage();

const posts = [];
page.on('response', (res) => {
  if (res.url().includes('/voice/transcribe')) posts.push(`${res.status()} ${res.url().slice(-40)}`);
});

await page.goto(`${BASE}/auth/signin`, { waitUntil: 'domcontentloaded' });
await page.evaluate(
  async ({ username, password }) => {
    const res = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: username, password, remember_me: false }),
    });
    const body = await res.json();
    localStorage.setItem('agentium_token', `Bearer ${body.token}`);
    if (body.refresh_token) localStorage.setItem('agentium_refresh_token', body.refresh_token);
    localStorage.setItem('agentium_workspace_slug', 'nawa');
  },
  { username: USER, password: PASS },
);

await page.goto(`${BASE}/nawa/itsd/assistant`, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.as-composer', { timeout: 60000 });
await page.waitForTimeout(1200);

const composer = page.locator('.as-composer');
const box = page.locator('.as-composer textarea');

await page.locator('.as-mic').click();
console.log('micro ouvert, le fichier joue');

for (const at of [2200, 2000, 2000]) {
  await page.waitForTimeout(at);
  const heard = await box.inputValue();
  console.log(`t+${at}ms — invite : "${heard}"`);
  await composer.screenshot({ path: `/tmp/voice-${at}.png` });
}

// Reprendre la main au clavier : l'écoute s'arrête, les mots restent.
await box.click();
await page.waitForTimeout(2000);
const kept = await box.inputValue();
const micLabel = (await page.locator('.as-mic').textContent()).trim();
console.log(`après clic dans le champ — invite : "${kept}"`);
console.log(`bouton micro : "${micLabel}"`);
await composer.screenshot({ path: '/tmp/voice-takeover.png' });

console.log('appels de transcription :', posts.length);
posts.forEach((p) => console.log('  ', p));

await browser.close();
