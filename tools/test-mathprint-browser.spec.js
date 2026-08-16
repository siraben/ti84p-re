const fs = require('fs');
const http = require('http');
const path = require('path');
const crypto = require('crypto');
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
const verticalViewportOracle = JSON.parse(fs.readFileSync(path.join(
  __dirname, 'mathprint-vertical-viewport-oracle.json'))).cases[0];

let server;
let baseUrl;

function delay(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

test.beforeAll(async () => {
  if (process.env.MATHPRINT_TEST_URL) {
    baseUrl = process.env.MATHPRINT_TEST_URL;
    return;
  }
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
  await expect(input).not.toHaveAttribute('maxlength');
  await input.pressSequentially(doubledIntegral);
  await expect(input).toHaveValue(doubledIntegral);
  await expect(page.locator('#err')).toHaveText('');
  await expect(page.locator('#dims')).toContainText('106 px record extent');
  await expect(page.locator('#dims')).toContainText('10 px wider than viewport');
  await expect(page.locator('#dims')).toContainText('editor x clip 17 px');
  await expect(page.locator('#timeline-note')).toContainText(
    'The expression remains complete in the input field');
  await expect(page.locator('#timeline-note')).toContainText(
    'select Model elements to inspect the full unscrolled equation');
  await expect(page.locator('#screen')).toHaveAttribute('width', '600');
  await expect(page.locator('#screen')).toHaveAttribute('height', '408');
  expect(await page.locator('#timeline').evaluate(element => ({
    maximum:Number(element.max), value:Number(element.value),
  }))).toEqual({maximum:198, value:198});
  await page.locator('#source').selectOption('model');
  await expect(page.locator('#dims')).toHaveText(
    '103×23 model pixels · 106 px record extent · ' +
    '10 px wider than 96 px LCD · editor x clip 17 px');
  await expect(page.locator('#screen')).toHaveAttribute('width', '666');
  await expect(page.locator('#screen')).toHaveAttribute('height', '186');
  expect(pageErrors).toEqual([]);
});

test('renders the depth-four vertical viewport at calculator pixels',
  async ({ page }) => {
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(String(error)));
    await page.goto(baseUrl, {waitUntil:'domcontentloaded'});
    await page.locator('#expr').fill(verticalViewportOracle.expression);
    await expect(page.locator('#err')).toHaveText('');
    await expect(page.locator('#dims')).toContainText('editor y clip 8 px');
    await expect(page.locator('#dims')).toContainText('write 119/119');

    const grid = await page.locator('#screen').evaluate((canvas) => {
      const context = canvas.getContext('2d');
      const pixels = context.getImageData(
        0, 0, canvas.width, canvas.height).data;
      const background = Array.from(pixels.slice(0, 4));
      const scale = 6, pad = 2, width = 96, height = 64;
      return Array.from({length:height}, (_, y) =>
        Array.from({length:width}, (_, x) => {
          const sampleX = Math.floor((x + pad + 0.5) * scale);
          const sampleY = Math.floor((y + pad + 0.5) * scale);
          const offset = 4 * (sampleY * canvas.width + sampleX);
          return background.some((value, channel) =>
            pixels[offset + channel] !== value) ? 1 : 0;
        }));
    });
    expect(crypto.createHash('sha256').update(
      Buffer.from(grid.flat())).digest('hex'))
      .toBe(verticalViewportOracle.full_lcd.sha256);
    // The ROM draws the two viewport arrows near the screen center after the
    // settled expression. Restrict the independent entry crop to the pixels
    // left of that chrome before comparing its compact oracle.
    const entryGrid = grid.map(row => row.slice(0,44));
    const occupied = entryGrid.flatMap((row, y) =>
      row.flatMap((value, x) => value ? [[x,y]] : []));
    const left = Math.min(...occupied.map(([x]) => x));
    const right = Math.max(...occupied.map(([x]) => x));
    const top = Math.min(...occupied.map(([,y]) => y));
    const bottom = Math.max(...occupied.map(([,y]) => y));
    const crop = entryGrid.slice(top,bottom + 1).map(row =>
      row.slice(left,right + 1));
    expect({
      width:right - left + 1,
      height:bottom - top + 1,
      sha256:crypto.createHash('sha256').update(
        Buffer.from(crop.flat())).digest('hex'),
    }).toEqual({
      width:verticalViewportOracle.entry_crop.width,
      height:verticalViewportOracle.entry_crop.height,
      sha256:verticalViewportOracle.entry_crop.sha256,
    });
    expect(pageErrors).toEqual([]);
  });

test('keeps growing the model and LCD viewport after a second overflow',
  async ({ page }) => {
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(String(error)));
    const integral = 'int(1,3,(1//2)X,X)';
    await page.goto(baseUrl, {waitUntil:'domcontentloaded'});
    const input = page.locator('#expr');
    await expect(page.locator('#dims')).not.toHaveText('');
    await input.fill('');
    await input.pressSequentially(integral);
    await expect(page.locator('#dims')).toContainText('50 px record extent');
    await input.pressSequentially(`+${integral}`);
    await expect(page.locator('#dims')).toContainText('106 px record extent');
    await expect(page.locator('#dims')).toContainText('editor x clip 17 px');
    await input.pressSequentially(`+${integral}`);
    await expect(input).toHaveValue(`${doubledIntegral}+${integral}`);
    await expect(page.locator('#err')).toHaveText('');
    await expect(page.locator('#dims')).toContainText('162 px record extent');
    await expect(page.locator('#dims')).toContainText('66 px wider than viewport');
    await expect(page.locator('#dims')).toContainText('editor x clip 73 px');
    await expect(page.locator('#timeline-note')).toContainText(
      'The expression remains complete in the input field');
    await expect(page.locator('#screen')).toHaveAttribute('width', '600');
    await expect(page.locator('#screen')).toHaveAttribute('height', '408');
    expect(await page.locator('#timeline').evaluate(element => ({
      maximum:Number(element.max), value:Number(element.value),
    }))).toEqual({maximum:198, value:198});
    const rgba = await page.locator('#screen').evaluate(canvas =>
      Array.from(canvas.getContext('2d').getImageData(
        0, 0, canvas.width, canvas.height).data));
    expect(crypto.createHash('sha256').update(Buffer.from(rgba)).digest('hex'))
      .toBe('3385da78a46c0c334432e3b8744cc2632a2fb2732089c1f38a972697577a8d9c');
    await page.locator('#source').selectOption('model');
    await expect(page.locator('#dims')).toHaveText(
      '159×23 model pixels · 162 px record extent · ' +
      '66 px wider than 96 px LCD · editor x clip 73 px');
    await expect(page.locator('#screen')).toHaveAttribute('width', '1002');
    await expect(page.locator('#screen')).toHaveAttribute('height', '186');
    const modelStage = await page.locator('.stage').evaluate(element => ({
      clientWidth:element.clientWidth,
      scrollWidth:element.scrollWidth,
      maximumScroll:element.scrollWidth - element.clientWidth,
    }));
    expect(modelStage.scrollWidth).toBeGreaterThanOrEqual(1050);
    expect(modelStage.maximumScroll).toBeGreaterThanOrEqual(232);
    const modelRgba = await page.locator('#screen').evaluate(canvas =>
      Array.from(canvas.getContext('2d').getImageData(
        0, 0, canvas.width, canvas.height).data));
    expect(crypto.createHash('sha256').update(Buffer.from(modelRgba)).digest('hex'))
      .toBe('0764c5bd5a9a1639ea8056cf5d4fa2b34c2628d120da30d0dfe1016129005542');
    expect(pageErrors).toEqual([]);
  });

test('retains, resets, and regrows the ROM viewport across long edits',
  async ({ page }) => {
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(String(error)));
    const integral = 'int(1,3,(1//2)X,X)';
    const repeated = count => new Array(count).fill(integral).join('+');
    await page.setViewportSize({width:480,height:900});
    await page.goto(baseUrl, {waitUntil:'domcontentloaded'});
    const input = page.locator('#expr');
    await expect(page.locator('#dims')).not.toHaveText('');

    await input.fill(repeated(3));
    await expect(page.locator('#dims')).toContainText('162 px record extent');
    await expect(page.locator('#dims')).toContainText('editor x clip 73 px');

    // 34:5F5D does not move an existing clip left merely because the edited
    // endpoint shrank. It clears only once the endpoint lies left of the clip.
    await input.fill(repeated(2));
    await expect(page.locator('#dims')).toContainText('106 px record extent');
    await expect(page.locator('#dims')).toContainText('editor x clip 73 px');
    await input.fill(integral);
    await expect(page.locator('#dims')).toContainText('50 px record extent');
    await expect(page.locator('#dims')).not.toContainText('wider than');
    await input.fill(repeated(2));
    await expect(page.locator('#dims')).toContainText('editor x clip 17 px');

    const initialHeight = await input.evaluate(element => element.clientHeight);
    await input.fill(repeated(8));
    await expect(input).toHaveValue(repeated(8));
    await expect(page.locator('#err')).toHaveText('');
    await expect(page.locator('#dims')).toContainText('442 px record extent');
    await expect(page.locator('#dims')).toContainText('editor x clip 353 px');
    const inputBox = await input.evaluate(element => ({
      clientHeight:element.clientHeight,
      scrollHeight:element.scrollHeight,
      maximumHeight:Number.parseFloat(getComputedStyle(element).maxHeight),
    }));
    expect(inputBox.clientHeight).toBeGreaterThan(initialHeight);
    expect(inputBox.clientHeight).toBeLessThanOrEqual(inputBox.maximumHeight);
    expect(inputBox.scrollHeight).toBeLessThanOrEqual(inputBox.clientHeight + 2);
    expect(await page.locator('#timeline').evaluate(element => Number(element.max)))
      .toBeGreaterThan(0);
    expect(pageErrors).toEqual([]);
  });
