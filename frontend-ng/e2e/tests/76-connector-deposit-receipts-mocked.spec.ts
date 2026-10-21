import { expect, test } from '@playwright/test';

// Real browser, synthetic uploads and entirely mocked HTTP. No external service is contacted.
test.use({ viewport: { width: 320, height: 820 }, serviceWorkers: 'block', video: 'off' });

for (const locale of ['fr', 'en'] as const) {
  test(`guest deposit keeps the accepted and refused file receipts separate at 320 px (${locale})`, async ({ page }) => {
    const uploads: string[] = [];
    await page.addInitScript(locale => {
      sessionStorage.setItem('deposit:receipt-fixture:token', 'fixture-session');
      localStorage.setItem('agentium_locale', locale);
      localStorage.setItem('agentium_theme', 'light');
    }, locale);
    await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort());
    await page.route('**/api/v1/**', async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path.endsWith('/deposit-links/receipt-fixture/files')) {
        if (request.method() === 'POST') {
          const body = request.postDataBuffer()?.toString() ?? '';
          const filename = body.includes('refused.exe') ? 'refused.exe' : 'received.txt';
          uploads.push(filename);
          return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ file: {
            id: filename, filename, status: filename === 'refused.exe' ? 'rejected' : 'received',
            rejection_reason: filename === 'refused.exe' ? 'Executable files are not allowed.' : null,
          } }) });
        }
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ link: {
          label: 'Guest document deposit', access_id: 'receipt-fixture', status: 'active', expires_at: null,
          max_file_size_mb: 10, allowed_extensions: ['txt'], workspace_name: 'Receipt fixture',
        }, files: [] }) });
      }
      return route.fulfill({ contentType: 'application/json', body: '{}' });
    });
    await page.goto('/deposit/receipt-fixture');
    await expect(page.getByRole('heading', { name: 'Guest document deposit' })).toBeVisible();
    await page.locator('input[type=file]').setInputFiles([
      { name: 'received.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetic document') },
      { name: 'refused.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('Synthetic refusal') },
    ]);
    await page.getByRole('button', { name: locale === 'fr' ? 'Envoyer' : 'Upload', exact: true }).click();
    const receipt = page.getByTestId('deposit-receipt');
    await expect(receipt.locator('[data-state=received]')).toContainText('received.txt');
    await expect(receipt.locator('[data-state=rejected]')).toContainText('refused.exe');
    await expect(receipt.locator('[data-state=rejected]')).toContainText('Executable files are not allowed.');
    await expect(receipt).toContainText(locale === 'fr' ? 'promotion' : 'promotion');
    expect(uploads.sort()).toEqual(['received.txt', 'refused.exe']);
    await expect(page.getByRole('button', { name: locale === 'fr' ? 'Envoyer' : 'Upload', exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}
