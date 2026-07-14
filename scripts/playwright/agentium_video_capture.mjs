#!/usr/bin/env node
import { chromium } from 'playwright';
import { copyFile, mkdir, readFile, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(__dirname, '../..');
const defaultScenes = path.join(__dirname, 'agentium_video_scenes.json');

function arg(name, fallback = null) {
  const prefix = `--${name}=`;
  const found = process.argv.find((item) => item.startsWith(prefix));
  if (found) return found.slice(prefix.length);
  return fallback;
}

function hasFlag(name) {
  return process.argv.includes(`--${name}`);
}

function buildUrl(host, url, workspace) {
  const target = new URL(url.startsWith('http') ? url : `${host}${url}`);
  if (workspace && !target.searchParams.has('workspace')) {
    target.searchParams.set('workspace', workspace);
  }
  return target.toString();
}

async function installWorkspaceUrlBridge(target) {
  await target.addInitScript(() => {
    try {
      const workspaceSlug = new URLSearchParams(window.location.search).get('workspace');
      if (workspaceSlug) window.localStorage.setItem('agentium_workspace_slug', workspaceSlug);
    } catch {
      // Best effort only: normal app bootstrap will keep the existing workspace.
    }
  });
}

async function resolveSystemId(page, { host, workspace, systemName, systemSlug }) {
  if (!systemName && !systemSlug) return null;
  return await page.evaluate(
    async ({ apiHost, workspaceSlug, wantedName, wantedSlug }) => {
      if (workspaceSlug) {
        localStorage.setItem('agentium_workspace_slug', workspaceSlug);
      }
      const token = localStorage.getItem('agentium_token') || '';
      const headers = {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: token } : {}),
        ...(workspaceSlug ? { 'X-Workspace-Slug': workspaceSlug } : {}),
      };
      const res = await fetch(`${apiHost}/api/v1/systems`, { headers });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, status: res.status, body };
      const rows = Array.isArray(body) ? body : body.systems || body.items || [];
      const normalize = (value) => String(value || '').trim().toLowerCase();
      const name = normalize(wantedName);
      const slug = normalize(wantedSlug);
      const found = rows.find((row) => {
        const rowName = normalize(row.name);
        const rowSlug = normalize(row.slug || row.key || row.system_slug);
        return (name && rowName === name) || (slug && rowSlug === slug);
      }) || rows.find((row) => {
        const rowName = normalize(row.name);
        return name && rowName.includes(name);
      });
      if (!found?.id) {
        return { ok: false, status: 404, available: rows.map((row) => row.name || row.slug || row.id).filter(Boolean).slice(0, 20) };
      }
      return { ok: true, id: found.id, name: found.name || wantedName || wantedSlug };
    },
    { apiHost: host, workspaceSlug: workspace, wantedName: systemName || '', wantedSlug: systemSlug || '' },
  );
}

async function sceneUrl(page, scene, options, rawUrl = scene.url) {
  const workspace = scene.workspace || options.workspace;
  let url = rawUrl;
  if (url.includes('{systemId}') || scene.systemName || scene.systemSlug) {
    await page.evaluate((workspaceSlug) => {
      if (workspaceSlug) window.localStorage.setItem('agentium_workspace_slug', workspaceSlug);
    }, workspace).catch(() => {});
    if (page.url() === 'about:blank') {
      await page.goto(buildUrl(options.host, '/', workspace), { waitUntil: 'domcontentloaded', timeout: 60_000 });
    }
    const resolved = await resolveSystemId(page, {
      host: options.host,
      workspace,
      systemName: scene.systemName,
      systemSlug: scene.systemSlug,
    });
    if (!resolved?.ok || !resolved.id) {
      throw new Error(`Unable to resolve system for scene ${scene.id}: ${JSON.stringify(resolved)}`);
    }
    url = url.replaceAll('{systemId}', encodeURIComponent(resolved.id));
  }
  return buildUrl(options.host, url, workspace);
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

function routePath(route) {
  try {
    return new URL(route, 'https://capture.local').pathname;
  } catch {
    return route;
  }
}

function escapeRegex(text) {
  return String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function authenticate(browser, { host, email, password, workspace, outDir }) {
  if (!email || !password) {
    throw new Error(
      'AGENTIUM_EMAIL and AGENTIUM_PASSWORD are required. Export them in your shell; do not commit them.',
    );
  }
  const statePath = path.join(outDir, 'auth-state.json');
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  await page.goto(`${host}/auth/signin`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  const login = await page.evaluate(
    async ({ userEmail, userPassword, workspaceSlug }) => {
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: userEmail, password: userPassword, remember_me: false }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok || !body.token) return { ok: false, status: res.status, body };
      localStorage.setItem('agentium_token', `Bearer ${body.token}`);
      if (body.refresh_token) localStorage.setItem('agentium_refresh_token', body.refresh_token);
      localStorage.setItem('agentium_workspace_slug', workspaceSlug);
      return { ok: true, status: res.status, workspace_slug: body.workspace_slug, workspace_count: Array.isArray(body.workspaces) ? body.workspaces.length : null };
    },
    { userEmail: email, userPassword: password, workspaceSlug: workspace },
  );
  if (!login.ok) {
    await page.screenshot({ path: path.join(outDir, 'login-failed.png') }).catch(() => {});
    await context.close();
    throw new Error(`Login failed: ${JSON.stringify(login)}`);
  }
  await context.storageState({ path: statePath });
  await context.close();
  return { statePath, login };
}

async function humanPause(page, ms = 350) {
  await page.waitForTimeout(ms);
}

async function clickRoute(page, step) {
  if (step.expandRail) {
    const rail = page.locator('app-side-rail aside, .ck-rail').first();
    if (await rail.isVisible({ timeout: 1200 }).catch(() => false)) {
      await rail.hover();
      await humanPause(page, 520);
    }
  }

  const route = routePath(step.route || '');
  const candidates = [];
  if (route) {
    candidates.push(`a[href="${route}"]`);
    candidates.push(`a[href^="${route}?"]`);
  }
  if (step.selector) candidates.unshift(step.selector);

  for (const selector of candidates) {
    const loc = page.locator(selector).first();
    if (!(await loc.isVisible({ timeout: 1000 }).catch(() => false))) continue;
    await loc.scrollIntoViewIfNeeded().catch(() => {});
    await loc.hover().catch(() => {});
    await humanPause(page, 220);
    await loc.click({ timeout: step.timeoutMs || 10_000 });
    await page.waitForLoadState('domcontentloaded', { timeout: 20_000 }).catch(() => {});
    await humanPause(page, step.waitMs || 1400);
    return { ok: true, selector };
  }

  if (step.label) {
    const name = new RegExp(escapeRegex(step.label), 'i');
    for (const role of ['link', 'button']) {
      const loc = page.getByRole(role, { name }).first();
      if (!(await loc.isVisible({ timeout: 1000 }).catch(() => false))) continue;
      await loc.scrollIntoViewIfNeeded().catch(() => {});
      await loc.hover().catch(() => {});
      await humanPause(page, 220);
      await loc.click({ timeout: step.timeoutMs || 10_000 });
      await page.waitForLoadState('domcontentloaded', { timeout: 20_000 }).catch(() => {});
      await humanPause(page, step.waitMs || 1400);
      return { ok: true, role, label: step.label };
    }
    const textTarget = page.getByText(name).first();
    if (await textTarget.isVisible({ timeout: 1000 }).catch(() => false)) {
      const clickable = textTarget.locator('xpath=ancestor-or-self::*[self::a or self::button][1]').first();
      const target = (await clickable.count().catch(() => 0)) ? clickable : textTarget;
      await target.scrollIntoViewIfNeeded().catch(() => {});
      await target.hover().catch(() => {});
      await humanPause(page, 280);
      await target.click({ timeout: step.timeoutMs || 10_000 });
      await page.waitForLoadState('domcontentloaded', { timeout: 20_000 }).catch(() => {});
      await humanPause(page, step.waitMs || 1400);
      return { ok: true, text: step.label };
    }
  }

  return { ok: false, error: `No visible nav target for ${step.label || step.route || 'step'}` };
}

async function navigateScene(page, scene, options, previousWorkspace) {
  const workspace = scene.workspace || options.workspace;
  await page.evaluate((workspaceSlug) => {
    window.localStorage.setItem('agentium_workspace_slug', workspaceSlug);
  }, workspace).catch(() => {});
  const url = await sceneUrl(page, scene, options);
  const result = { url, workspace, mode: 'direct', steps: [] };
  const startUrl = scene.startUrl ? await sceneUrl(page, scene, options, scene.startUrl) : null;

  const canUseUi =
    (startUrl || (options.continuous && previousWorkspace === workspace)) &&
    Array.isArray(scene.navSteps) &&
    scene.navSteps.length > 0;

  if (canUseUi) {
    result.mode = startUrl ? 'ui_from_start' : 'ui';
    const currentPath = routePath(page.url());
    const startPath = startUrl ? routePath(startUrl) : null;
    const keepCurrentPage = Boolean(
      startUrl
      && options.continuous
      && previousWorkspace === workspace
      && currentPath === startPath,
    );
    if (startUrl && !keepCurrentPage) {
      await page.goto(startUrl, { waitUntil: 'domcontentloaded', timeout: 60_000 });
      await humanPause(page, Number(scene.startWaitMs || 1300));
    } else if (keepCurrentPage) {
      result.mode = 'ui_from_current';
    }
    for (const step of scene.navSteps) {
      const resolvedStep = { ...step };
      if (resolvedStep.route && String(resolvedStep.route).includes('{systemId}')) {
        resolvedStep.route = await sceneUrl(page, scene, options, resolvedStep.route);
      }
      const stepResult = await clickRoute(page, resolvedStep);
      result.steps.push({ step: resolvedStep, ...stepResult });
      if (!stepResult.ok) {
        result.mode = 'ui_fallback_direct';
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60_000 });
        await humanPause(page, 1400);
        return result;
      }
    }
    return result;
  }

  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await humanPause(page, 1200);
  return result;
}

async function applyAction(page, action) {
  if (action.type === 'wait') {
    await page.waitForTimeout(action.waitMs || 1000);
    return { ok: true };
  }
  if (action.type === 'style') {
    await page.addStyleTag({ content: action.css || '' });
    if (action.waitMs) await page.waitForTimeout(action.waitMs);
    return { ok: true };
  }
  if (action.type === 'hover') {
    const loc = page.locator(action.selector).first();
    await loc.scrollIntoViewIfNeeded().catch(() => {});
    await loc.hover({ timeout: action.timeoutMs || 10_000 });
    if (action.waitMs) await page.waitForTimeout(action.waitMs);
    return { ok: true };
  }
  if (action.type === 'scroll') {
    await page.mouse.wheel(Number(action.deltaX || 0), Number(action.deltaY || 520));
    if (action.waitMs) await page.waitForTimeout(action.waitMs);
    return { ok: true };
  }
  if (action.type === 'clickRole') {
    const role = action.role || 'button';
    const name = new RegExp(action.regex ? String(action.name || '') : escapeRegex(action.name || ''), 'i');
    const loc = page.getByRole(role, { name }).first();
    await loc.scrollIntoViewIfNeeded().catch(() => {});
    await loc.hover().catch(() => {});
    await humanPause(page, 240);
    await loc.click({ timeout: action.timeoutMs || 10_000 });
    if (action.waitMs) await page.waitForTimeout(action.waitMs);
    return { ok: true };
  }
  if (action.type === 'click') {
    const loc = page.locator(action.selector).first();
    await loc.scrollIntoViewIfNeeded().catch(() => {});
    await loc.hover().catch(() => {});
    await humanPause(page, 220);
    await loc.click({ timeout: action.timeoutMs || 10_000 });
    if (action.waitMs) await page.waitForTimeout(action.waitMs);
    return { ok: true };
  }
  if (action.type === 'fill') {
    await page.locator(action.selector).first().fill(action.text || '', { timeout: action.timeoutMs || 10_000 });
    if (action.waitMs) await page.waitForTimeout(action.waitMs);
    return { ok: true };
  }
  if (action.type === 'press') {
    await page.locator(action.selector || 'body').first().press(action.key || 'Enter', { timeout: action.timeoutMs || 10_000 });
    if (action.waitMs) await page.waitForTimeout(action.waitMs);
    return { ok: true };
  }
  if (action.type === 'newChat') {
    const labels = ['New chat', 'New conversation', 'Nouveau chat', 'Nouvelle conversation', 'Start a conversation'];
    for (const label of labels) {
      const loc = page.getByRole('button', { name: new RegExp(escapeRegex(label), 'i') }).first();
      if (!(await loc.isVisible({ timeout: 800 }).catch(() => false))) continue;
      await loc.hover().catch(() => {});
      await humanPause(page, 260);
      await loc.click({ timeout: action.timeoutMs || 10_000 });
      await page.waitForTimeout(action.waitMs || 1400);
      return { ok: true, method: 'button', label };
    }
    const apiResult = await page.evaluate(async () => {
      const token = localStorage.getItem('agentium_token') || '';
      const workspaceSlug = localStorage.getItem('agentium_workspace_slug') || '';
      const res = await fetch('/api/v1/sessions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: token } : {}),
          ...(workspaceSlug ? { 'X-Workspace-Slug': workspaceSlug } : {}),
        },
        body: JSON.stringify({ context: { source: 'video_capture', language: 'en' } }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok || !body.id) return { ok: false, status: res.status, body };
      localStorage.setItem('agentium:selected-chat-session-id', body.id);
      return { ok: true, id: body.id };
    });
    if (!apiResult.ok) return { ok: false, warning: `New chat API failed: ${JSON.stringify(apiResult)}` };
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(action.waitMs || 1400);
    return { ok: true, method: 'api', id: apiResult.id };
  }
  if (action.type === 'chatPrompt') {
    const selectors = [
      'textarea[name="userInput"]',
      'textarea',
      '[contenteditable="true"]',
      'input[type="text"]',
    ];
    let input = null;
    for (const selector of selectors) {
      const candidate = page.locator(selector).first();
      if (await candidate.isVisible({ timeout: 1500 }).catch(() => false)) {
        input = candidate;
        break;
      }
    }
    if (!input) throw new Error('No visible chat input found');
    await input.fill(action.text || '');
    await page.waitForTimeout(250);
    await input.press('Enter');
    await page.waitForTimeout(action.waitMs || 10_000);
    return { ok: true };
  }
  return { ok: false, warning: `Unsupported action type: ${action.type}` };
}

async function viewportText(page) {
  return await page.evaluate(() => {
    const viewport = {
      left: 0,
      top: 0,
      right: window.innerWidth,
      bottom: window.innerHeight,
    };
    const visible = (element) => {
      if (!element || !(element instanceof HTMLElement)) return false;
      const style = window.getComputedStyle(element);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
      const rect = element.getBoundingClientRect();
      return rect.width > 0
        && rect.height > 0
        && rect.right >= viewport.left
        && rect.left <= viewport.right
        && rect.bottom >= viewport.top
        && rect.top <= viewport.bottom;
    };
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const chunks = [];
    let node = walker.nextNode();
    while (node) {
      const text = (node.nodeValue || '').replace(/\s+/g, ' ').trim();
      if (text && visible(node.parentElement)) chunks.push(text);
      node = walker.nextNode();
    }
    return chunks.join(' ');
  }).catch(() => '');
}

function evaluateTextChecks(result, scene, bodyText, filmedText) {
  const body = String(bodyText || '').toLowerCase();
  const viewport = String(filmedText || '').toLowerCase();
  for (const needle of scene.softChecks || []) {
    if (!body.includes(String(needle).toLowerCase())) {
      result.warnings.push(`Missing expected text: ${needle}`);
    }
  }
  for (const needle of scene.softForbidden || []) {
    if (viewport.includes(String(needle).toLowerCase())) {
      result.warnings.push(`Forbidden text visible in viewport: ${needle}`);
    }
  }
}

async function captureScene(browser, scene, options) {
  const sceneDir = path.join(options.outDir, 'scenes', scene.id);
  const screenshotDir = path.join(options.outDir, 'screenshots');
  const videoDir = path.join(options.outDir, 'video');
  await mkdir(sceneDir, { recursive: true });
  await mkdir(screenshotDir, { recursive: true });
  await mkdir(videoDir, { recursive: true });

  const context = await browser.newContext({
    storageState: options.statePath,
    viewport: { width: options.width, height: options.height },
    deviceScaleFactor: 1,
    locale: 'en-US',
    permissions: ['microphone'],
    ignoreHTTPSErrors: true,
    recordVideo: options.noVideo ? undefined : { dir: sceneDir, size: { width: options.width, height: options.height } },
  });
  await installWorkspaceUrlBridge(context);
  const page = await context.newPage();
  const result = {
    id: scene.id,
    title: scene.title,
    workspace: scene.workspace || options.workspace,
    url: null,
    ok: true,
    warnings: [],
    actionResults: [],
    screenshot: null,
    video: null,
  };
  let video = null;
  try {
    video = page.video();
    const workspace = scene.workspace || options.workspace;
    await page.evaluate((workspaceSlug) => {
      window.localStorage.setItem('agentium_workspace_slug', workspaceSlug);
    }, workspace).catch(() => {});
    const navigation = await navigateScene(page, scene, { ...options, continuous: false }, null);
    result.url = navigation.url;
    result.navigation = navigation;
    await page.waitForTimeout(scene.waitMs || options.defaultWaitMs);
    for (const selector of scene.waitForSelectors || []) {
      await page.locator(selector).first().waitFor({ state: 'visible', timeout: 15_000 });
    }
    for (const action of scene.actions || []) {
      try {
        result.actionResults.push({ action, ...(await applyAction(page, action)) });
      } catch (err) {
        const actionResult = { action, ok: false, error: err.message };
        result.actionResults.push(actionResult);
        if (action.optional) {
          result.warnings.push(`Optional action failed: ${err.message}`);
        } else {
          result.ok = false;
        }
      }
    }
    const text = await page.locator('body').innerText({ timeout: 10_000 }).catch(() => '');
    const filmedText = await viewportText(page);
    evaluateTextChecks(result, scene, text, filmedText);
    const screenshot = path.join(screenshotDir, `${scene.id}.png`);
    await page.screenshot({ path: screenshot, fullPage: false });
    result.screenshot = screenshot;
  } catch (err) {
    result.ok = false;
    result.error = err.message;
    await page.screenshot({ path: path.join(screenshotDir, `${scene.id}-error.png`), fullPage: false }).catch(() => {});
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
    if (video && !options.noVideo) {
      const rawPath = await video.path().catch(() => null);
      const finalPath = path.join(videoDir, `${scene.id}.webm`);
      if (rawPath) {
        await copyFile(rawPath, finalPath).catch(async () => {
          await video.saveAs(finalPath);
        });
      } else {
        await video.saveAs(finalPath).catch((err) => {
          result.warnings.push(`Video save failed: ${err.message}`);
        });
      }
      result.video = finalPath;
    }
  }
  return result;
}

async function evaluateScene(page, scene, options, navigationResult) {
  const screenshotDir = path.join(options.outDir, 'screenshots');
  await mkdir(screenshotDir, { recursive: true });
  const result = {
    id: scene.id,
    title: scene.title,
    workspace: scene.workspace || options.workspace,
    url: navigationResult.url,
    ok: true,
    warnings: [],
    actionResults: [],
    screenshot: null,
    video: options.continuousVideo || null,
    navigation: navigationResult,
  };
  try {
    await page.waitForTimeout(scene.waitMs || options.defaultWaitMs);
    for (const selector of scene.waitForSelectors || []) {
      await page.locator(selector).first().waitFor({ state: 'visible', timeout: 15_000 });
    }
    for (const action of scene.actions || []) {
      try {
        result.actionResults.push({ action, ...(await applyAction(page, action)) });
      } catch (err) {
        const actionResult = { action, ok: false, error: err.message };
        result.actionResults.push(actionResult);
        if (action.optional) {
          result.warnings.push(`Optional action failed: ${err.message}`);
        } else {
          result.ok = false;
        }
      }
    }
    const text = await page.locator('body').innerText({ timeout: 10_000 }).catch(() => '');
    const filmedText = await viewportText(page);
    evaluateTextChecks(result, scene, text, filmedText);
    const screenshot = path.join(screenshotDir, `${scene.id}.png`);
    await page.screenshot({ path: screenshot, fullPage: false });
    result.screenshot = screenshot;
  } catch (err) {
    result.ok = false;
    result.error = err.message;
    await page.screenshot({ path: path.join(screenshotDir, `${scene.id}-error.png`), fullPage: false }).catch(() => {});
  }
  return result;
}

async function captureContinuous(browser, scenes, options) {
  const videoDir = path.join(options.outDir, 'video');
  await mkdir(videoDir, { recursive: true });
  const context = await browser.newContext({
    storageState: options.statePath,
    viewport: { width: options.width, height: options.height },
    deviceScaleFactor: options.deviceScaleFactor,
    locale: 'en-US',
    permissions: ['microphone'],
    ignoreHTTPSErrors: true,
    recordVideo: options.noVideo ? undefined : { dir: videoDir, size: { width: options.width, height: options.height } },
  });
  await installWorkspaceUrlBridge(context);
  const page = await context.newPage();
  const video = page.video();
  const results = [];
  let previousWorkspace = null;
  try {
    for (const scene of scenes) {
      console.log(`Capturing ${scene.id} - ${scene.title || scene.url}`);
      const sceneStartedAtMs = Date.now();
      const nav = await navigateScene(page, scene, options, previousWorkspace);
      const result = await evaluateScene(page, scene, options, nav);
      result.startedAtMs = sceneStartedAtMs;
      result.endedAtMs = Date.now();
      results.push(result);
      previousWorkspace = scene.workspace || options.workspace;
      console.log(`  ${result.ok ? 'OK' : 'FAIL'} nav=${nav.mode} warnings=${result.warnings.length} screenshot=${result.screenshot || '-'}`);
    }
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
  let finalVideo = null;
  if (video && !options.noVideo) {
    finalVideo = path.join(videoDir, 'walkthrough.webm');
    await video.saveAs(finalVideo).catch((err) => {
      results.push({
        id: 'continuous-video-save',
        ok: false,
        warnings: [],
        error: err.message,
      });
    });
    await video.delete().catch(() => {});
    for (const result of results) {
      if (result.id !== 'continuous-video-save') result.video = finalVideo;
    }
  }
  return { results, video: finalVideo };
}

async function main() {
  const host = (arg('host', process.env.AGENTIUM_HOST || 'https://agentium.papai.ai') || '').replace(/\/+$/, '');
  const email = arg('email', process.env.AGENTIUM_EMAIL || '');
  const password = process.env.AGENTIUM_PASSWORD || '';
  const workspace = arg('workspace', process.env.AGENTIUM_WORKSPACE || 'agentium-showcase');
  const scenesPath = path.resolve(arg('scenes', process.env.SCENES_FILE || defaultScenes));
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const outDir = path.resolve(arg('out-dir', process.env.OUT_DIR || path.join(repo, 'docs/video-captures', `capture-${stamp}`)));
  const viewport = viewportFromArgs();
  const width = viewport.width;
  const height = viewport.height;
  const deviceScaleFactor = Number(arg('scale', process.env.CAPTURE_DEVICE_SCALE_FACTOR || '1'));
  const defaultWaitMs = Number(arg('wait-ms', process.env.CAPTURE_WAIT_MS || '4000'));
  const sceneFilter = arg('scene', null);
  const noVideo = hasFlag('no-video');
  const keepAuthState = hasFlag('keep-auth-state');
  const continuous = hasFlag('continuous');
  await mkdir(outDir, { recursive: true });

  const scenes = JSON.parse(await readFile(scenesPath, 'utf8')).filter((scene) => !sceneFilter || scene.id === sceneFilter);
  if (scenes.length === 0) {
    throw new Error(`No scenes matched. scenes=${scenesPath} scene=${sceneFilter || '*'}`);
  }

  const manifest = {
    startedAt: new Date().toISOString(),
    host,
    email,
    workspace,
    scenesPath,
    outDir,
    viewport: { preset: viewport.preset, width, height, deviceScaleFactor },
    mode: continuous ? 'continuous' : 'separate',
    results: [],
  };
  let authStatePath = null;

  const browser = await chromium.launch({
    headless: !hasFlag('headed'),
    slowMo: Number(arg('slow-mo', process.env.SLOW_MO || '0')),
    args: [
      '--autoplay-policy=no-user-gesture-required',
      '--use-fake-device-for-media-stream',
      '--use-fake-ui-for-media-stream',
    ],
  });
  try {
    const auth = await authenticate(browser, { host, email, password, workspace, outDir });
    manifest.login = auth.login;
    authStatePath = auth.statePath;
    manifest.authStatePath = keepAuthState ? auth.statePath : '(deleted after capture)';
    if (continuous) {
      const continuousCapture = await captureContinuous(browser, scenes, {
        host,
        workspace,
        statePath: auth.statePath,
        outDir,
        width,
        height,
        deviceScaleFactor,
        defaultWaitMs,
        noVideo,
        continuous: true,
      });
      manifest.continuousVideo = continuousCapture.video;
      manifest.results.push(...continuousCapture.results);
    } else {
      for (const scene of scenes) {
        console.log(`Capturing ${scene.id} - ${scene.title || scene.url}`);
        const result = await captureScene(browser, scene, {
          host,
          workspace,
          statePath: auth.statePath,
          outDir,
          width,
          height,
          defaultWaitMs,
          noVideo,
        });
        manifest.results.push(result);
        console.log(`  ${result.ok ? 'OK' : 'FAIL'} warnings=${result.warnings.length} screenshot=${result.screenshot || '-'}`);
      }
    }
  } finally {
    await browser.close();
  }
  if (!keepAuthState && authStatePath) {
    await unlink(authStatePath).catch(() => {});
  }

  const manifestPath = path.join(outDir, 'capture-manifest.json');
  await writeFile(manifestPath, JSON.stringify(manifest, null, 2));
  const failed = manifest.results.filter((result) => !result.ok).length;
  const warnings = manifest.results.reduce((total, result) => total + result.warnings.length, 0);
  console.log(`Capture complete: ${manifest.results.length - failed} ok / ${failed} failed / ${warnings} warnings`);
  console.log(`Manifest: ${manifestPath}`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
