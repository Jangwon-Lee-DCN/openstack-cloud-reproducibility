const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const username = process.env.TEST_USERNAME;
  const password = process.env.TEST_PASSWORD;
  assert(username && password, 'transient test credentials are required');
  const cloud = 'https://cloud.dcn.ssu.ac.kr';
  const auth = 'https://auth.cloud.dcn.ssu.ac.kr';
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({ignoreHTTPSErrors: true, viewport: {width: 1440, height: 900}});
  const page = await context.newPage();
  const failures = [];
  page.on('console', m => { if (m.type() === 'error') failures.push(`console: ${m.text()}`); });
  page.on('pageerror', e => failures.push(`pageerror: ${e.message}`));
  page.on('response', r => {
    if ((r.url().startsWith(cloud) || r.url().startsWith(auth)) && r.status() >= 400)
      failures.push(`http ${r.status()}: ${r.url()}`);
  });

  await page.goto(`${cloud}/horizon`, {waitUntil: 'networkidle'});
  assert.equal(new URL(page.url()).origin, cloud, `Horizon entry left the dashboard origin: ${page.url()}`);
  assert.equal(new URL(page.url()).pathname, '/horizon/auth/login/', `Horizon entry did not reach its login page: ${page.url()}`);
  assert.equal(await page.locator('select[name="auth_type"]').inputValue(), 'keycloak_dcn');
  await page.locator('form').locator('button[type="submit"], input[type="submit"]').click();
  await page.waitForURL(url => url.origin === auth, {timeout: 30000});
  await page.getByText('DCN OpenStack', {exact: false}).first().waitFor();
  assert.equal(await page.getByText('Keycloak', {exact: false}).count(), 0);
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole('button', {name: /sign in|log in|로그인/i}).click();
  try {
    await page.waitForURL(url => url.origin === cloud && url.pathname.startsWith('/horizon/'), {timeout: 60000});
  } catch (error) {
    console.error(`login remained at ${page.url()}`);
    console.error((await page.locator('body').innerText()).slice(0, 2000));
    const cookies = await context.cookies();
    console.error(`cookie metadata: ${JSON.stringify(cookies.map(({name, domain, path, sameSite, secure}) => ({name, domain, path, sameSite, secure})))}`);
    console.error(`request failures: ${failures.join(' | ')}`);
    throw error;
  }
  await page.locator('body').waitFor();
  const body = await page.locator('body').innerText();
  assert(!/Something went wrong|Internal Server Error|Unable to retrieve|Forbidden|권한 오류/i.test(body), body.slice(0, 2000));
  await page.reload({waitUntil: 'networkidle'});
  assert(new URL(page.url()).pathname.startsWith('/horizon/'), `refresh lost the Horizon session: ${page.url()}`);
  await page.goto(`${cloud}/horizon/project/instances/`, {waitUntil: 'networkidle'});
  const deepLinkBody = await page.locator('body').innerText();
  assert.equal(new URL(page.url()).origin, cloud, `deep link left Horizon: ${page.url()}`);
  assert(!/Something went wrong|Internal Server Error|Forbidden|권한 오류/i.test(deepLinkBody), deepLinkBody.slice(0, 2000));
  assert.equal(failures.length, 0, failures.join('\n'));

  await context.clearCookies();
  await page.goto(`${cloud}/horizon`, {waitUntil: 'networkidle'});
  assert.equal(new URL(page.url()).origin, cloud, `fresh Horizon entry auto-redirected: ${page.url()}`);
  await page.locator('select[name="auth_type"]').selectOption('keycloak_dcn');
  await page.locator('form').locator('button[type="submit"], input[type="submit"]').click();
  await page.waitForURL(url => url.origin === auth, {timeout: 30000});
  const google = page.getByRole('link', {name: /google/i});
  await google.waitFor();
  const assertLoginLayout = async () => {
    const button = await google.boundingBox();
    const icon = await google.locator('svg').boundingBox();
    assert(button && button.height >= 40 && button.height <= 56, `invalid Google button bounds: ${JSON.stringify(button)}`);
    assert(icon && icon.width <= 24 && icon.height <= 24, `oversized Google icon: ${JSON.stringify(icon)}`);
    assert((await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)), 'login page overflows horizontally');
  };
  await assertLoginLayout();
  await page.setViewportSize({width: 390, height: 844});
  await assertLoginLayout();
  const request = page.waitForRequest(r => r.url().startsWith('https://accounts.google.com/'));
  await google.click({noWaitAfter: true});
  assert.match((await request).url(), /^https:\/\/accounts\.google\.com\//);
  await browser.close();
  console.log('production-unified-login-browser-e2e-passed');
})().catch(e => { console.error(e); process.exit(1); });
