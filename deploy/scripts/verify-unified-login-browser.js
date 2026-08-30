const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const username = process.env.TEST_USERNAME;
  const password = process.env.TEST_PASSWORD;
  assert(username && password, 'transient test credentials are required');
  const cloud = 'https://cloud.dcn.ssu.ac.kr';
  const auth = 'https://auth.cloud.dcn.ssu.ac.kr';
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({ignoreHTTPSErrors: true});
  const page = await context.newPage();
  const failures = [];
  page.on('console', m => { if (m.type() === 'error') failures.push(`console: ${m.text()}`); });
  page.on('pageerror', e => failures.push(`pageerror: ${e.message}`));
  page.on('response', r => {
    if ((r.url().startsWith(cloud) || r.url().startsWith(auth)) && r.status() >= 400)
      failures.push(`http ${r.status()}: ${r.url()}`);
  });

  await page.goto(`${cloud}/horizon/auth/login/`, {waitUntil: 'networkidle'});
  assert(page.url().startsWith(auth), `Horizon did not auto-redirect to the identity login: ${page.url()}`);
  await page.getByText('DCN OpenStack', {exact: false}).first().waitFor();
  assert.equal(await page.getByText('Keycloak', {exact: false}).count(), 0);
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole('button', {name: /sign in|log in|로그인/i}).click();
  await page.waitForURL(url => url.origin === cloud && url.pathname.startsWith('/horizon/'), {timeout: 60000});
  await page.locator('body').waitFor();
  const body = await page.locator('body').innerText();
  assert(!/Something went wrong|Internal Server Error|Unable to retrieve|권한 오류/i.test(body), body.slice(0, 2000));
  assert.equal(failures.length, 0, failures.join('\n'));

  await context.clearCookies();
  await page.goto(`${cloud}/horizon/auth/login/`, {waitUntil: 'networkidle'});
  const google = page.getByRole('link', {name: /google/i});
  await google.waitFor();
  const request = page.waitForRequest(r => r.url().startsWith('https://accounts.google.com/'));
  await google.click({noWaitAfter: true});
  assert.match((await request).url(), /^https:\/\/accounts\.google\.com\//);
  await browser.close();
  console.log('production-unified-login-browser-e2e-passed');
})().catch(e => { console.error(e); process.exit(1); });
