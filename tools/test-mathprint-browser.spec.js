const fs = require('fs');
const http = require('http');
const path = require('path');
const { test, expect } = require('@playwright/test');

const mathprintRoot = path.join(__dirname, '..', 'web', 'mathprint');
const delayedAssets = new Set([
  '/font.json', '/layout.json', '/draw-order.json', '/token-strings.json',
]);
const contentTypes = {
  '.css':'text/css; charset=utf-8',
  '.html':'text/html; charset=utf-8',
  '.js':'text/javascript; charset=utf-8',
  '.json':'application/json',
};
const doubledIntegral = 'int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)';

let server;
let baseUrl;

function delay(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

test.beforeAll(async () => {
  server = http.createServer(async (request, response) => {
    const pathname = new URL(request.url, 'http://127.0.0.1').pathname;
    if (delayedAssets.has(pathname)) await delay(350);
    const relative = pathname === '/' ? 'index.html' : pathname.slice(1);
    const target = path.resolve(mathprintRoot, relative);
    if (!target.startsWith(`${mathprintRoot}${path.sep}`)) {
      response.writeHead(403);
      response.end();
      return;
    }
    try {
      const body = await fs.promises.readFile(target);
      response.writeHead(200, {
        'content-type':contentTypes[path.extname(target)] ||
          'application/octet-stream',
      });
      response.end(body);
    } catch (error) {
      response.writeHead(error.code === 'ENOENT' ? 404 : 500);
      response.end();
    }
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      baseUrl = `http://127.0.0.1:${address.port}/`;
      resolve();
    });
  });
});

test.afterAll(async () => {
  if (server)
    await new Promise((resolve, reject) =>
      server.close(error => error ? reject(error) : resolve()));
});

test('preserves a long expression typed while assets load', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(String(error)));
  await page.goto(baseUrl, {waitUntil:'domcontentloaded'});
  const input = page.locator('#expr');
  await input.pressSequentially(doubledIntegral);
  await expect(input).toHaveValue(doubledIntegral);
  await expect(page.locator('#err')).toHaveText('');
  await expect(page.locator('#dims')).toContainText('106 px record extent');
  await expect(page.locator('#dims')).toContainText('10 px wider than viewport');
  await expect(page.locator('#dims')).toContainText('editor x clip 17 px');
  await expect(page.locator('#screen')).toHaveAttribute('width', '600');
  await expect(page.locator('#screen')).toHaveAttribute('height', '408');
  expect(await page.locator('#timeline').evaluate(element => ({
    maximum:Number(element.max), value:Number(element.value),
  }))).toEqual({maximum:198, value:198});
  expect(pageErrors).toEqual([]);
});

test('keeps growing the model and LCD viewport after a second overflow',
  async ({ page }) => {
    const expression = `${doubledIntegral}+int(1,3,(1//2)X,X)`;
    await page.goto(baseUrl, {waitUntil:'domcontentloaded'});
    const input = page.locator('#expr');
    await input.fill(expression);
    await expect(input).toHaveValue(expression);
    await expect(page.locator('#err')).toHaveText('');
    await expect(page.locator('#dims')).toContainText('162 px record extent');
    await expect(page.locator('#dims')).toContainText('66 px wider than viewport');
    await expect(page.locator('#dims')).toContainText('editor x clip 73 px');
  });
