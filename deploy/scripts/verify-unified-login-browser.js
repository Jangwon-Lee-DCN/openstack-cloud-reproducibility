const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const username = process.env.TEST_USERNAME;
  const password = process.env.TEST_PASSWORD;
  assert(username && password, 'transient test credentials are required');
  const cloud = 'https://cloud.dcn.ssu.ac.kr';
  const identityFrontend = `${cloud}/horizon/auth/idp`;
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({ignoreHTTPSErrors: true, viewport: {width: 1440, height: 900}});
  const page = await context.newPage();
  const failures = [];
  const expectedPortals = [
    ['Platform Monitoring', 'https://platform.dcn.ssu.ac.kr/grafana/'],
    ['Infrastructure Inventory', 'https://platform.dcn.ssu.ac.kr/netbox/'],
    ['Cloud Billing', 'https://billing.dcn.ssu.ac.kr/'],
    ['Source Code', 'https://platform.dcn.ssu.ac.kr/git/'],
    ['Container Registry', 'https://registry.dcn.ssu.ac.kr/'],
  ];
  page.on('console', m => { if (m.type() === 'error') failures.push(`console: ${m.text()}`); });
  page.on('pageerror', e => failures.push(`pageerror: ${e.message}`));
  page.on('request', r => {
    if (new URL(r.url()).hostname === 'auth.cloud.dcn.ssu.ac.kr')
      failures.push(`identity hostname escaped Horizon: ${r.url()}`);
  });
  page.on('response', r => {
    if (r.url().startsWith(cloud) && r.status() >= 400)
      failures.push(`http ${r.status()}: ${r.url()}`);
  });

  await page.goto(`${cloud}/horizon`, {waitUntil: 'networkidle'});
  assert.equal(new URL(page.url()).origin, cloud, `Horizon entry left the dashboard origin: ${page.url()}`);
  assert(page.url().startsWith(identityFrontend), `Horizon did not enter its same-origin identity frontend: ${page.url()}`);
  await page.getByText('Sign in to DCN Cloud', {exact: true}).waitFor();
  assert.equal(await page.getByText('DCN OpenStack', {exact: false}).count(), 0);
  for (const [name, href] of expectedPortals) {
    const link = page.getByRole('link', {name: new RegExp(name, 'i')});
    await link.waitFor();
    assert.equal(await link.getAttribute('href'), href);
    assert.equal(await link.getAttribute('target'), '_blank');
    const popup = page.waitForEvent('popup');
    await link.click();
    const opened = await popup;
    await opened.waitForLoadState('domcontentloaded');
    assert.notEqual(opened.url(), 'about:blank', `${name} did not navigate`);
    const response = await context.request.get(href, {
      failOnStatusCode: false,
      maxRedirects: 0,
      timeout: 30000,
    });
    assert(response.status() < 400, `${name} returned HTTP ${response.status()}: ${response.url()}`);
    const destinationBody = await opened.locator('body').innerText().catch(() => '');
    assert(!/Something went wrong|Internal Server Error|404 Not Found/i.test(destinationBody),
      `${name} opened an error page at ${opened.url()}: ${destinationBody.slice(0, 500)}`);
    console.log(`${name}: click=${opened.url()} status=${response.status()}`);
    await opened.close();
  }
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
  const bareMetalAccess = page.getByRole('link', {name: 'Bare Metal Access', exact: true});
  await bareMetalAccess.waitFor();
  await bareMetalAccess.click();
  await page.waitForURL(url => url.pathname.startsWith('/horizon/project/baremetal_access/'));
  await page.waitForLoadState('networkidle');
  const bareMetalBody = await page.locator('body').innerText();
  assert(/베어메탈 서버 사용 신청/.test(bareMetalBody), `Bare Metal request UI did not render: ${bareMetalBody.slice(0, 1000)}`);
  assert(!/Project\s*\/\s*Compute\s*\/\s*None/.test(bareMetalBody), 'Bare Metal breadcrumb contains None');
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Bare Metal page overflows horizontally');
  assert(!/Bare Metal Approvals/i.test(bareMetalBody), 'baseline DCN member received approval UI');
  assert.equal(failures.length, 0, failures.join('\n'));

  await page.locator('.user-menu .dropdown-toggle').click();
  await page.getByRole('button', {name: /sign out|log out|로그아웃/i}).click();
  await page.waitForURL(url => url.origin === cloud && url.pathname.startsWith('/horizon/auth/idp/'), {timeout: 60000});
  try {
    await page.getByText('Sign in to DCN Cloud', {exact: true}).waitFor();
  } catch (error) {
    console.error(`logout remained at ${page.url()}`);
    console.error((await page.locator('body').innerText()).slice(0, 2000));
    throw error;
  }
  const logoutBody = await page.locator('body').innerText();
  assert(!/Something went wrong|Internal Server Error|Forbidden|권한 오류/i.test(logoutBody), logoutBody.slice(0, 2000));
  const remainingCookies = await context.cookies();
  const sessionCookies = remainingCookies.filter(cookie =>
    cookie.name === 'sessionid' ||
    cookie.name.startsWith('mod_auth_openidc_session') ||
    cookie.name === 'KEYCLOAK_SESSION' ||
    cookie.name === 'KEYCLOAK_IDENTITY'
  );
  assert.equal(sessionCookies.length, 0, `logout retained authentication cookies: ${JSON.stringify(sessionCookies.map(({name, domain, path}) => ({name, domain, path})))}`);
  await page.goto(`${cloud}/horizon`, {waitUntil: 'networkidle'});
  assert(page.url().startsWith(identityFrontend), `logged-out Horizon entry restored the prior session: ${page.url()}`);
  assert.equal(failures.length, 0, failures.join('\n'));

  await context.clearCookies();
  await page.goto(`${cloud}/horizon`, {waitUntil: 'networkidle'});
  assert(page.url().startsWith(identityFrontend), `fresh Horizon entry left its same-origin identity frontend: ${page.url()}`);
  const google = page.getByRole('link', {name: /google/i});
  await google.waitFor();
  const assertLoginLayout = async () => {
    const button = await google.boundingBox();
    const icon = await google.locator('svg').boundingBox();
    assert(button && button.height >= 40 && button.height <= 56, `invalid Google button bounds: ${JSON.stringify(button)}`);
    assert(icon && icon.width <= 24 && icon.height <= 24, `oversized Google icon: ${JSON.stringify(icon)}`);
    assert((await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)), 'login page overflows horizontally');
    assert.equal(await page.locator('.dcn-resource-link').count(), expectedPortals.length);
  };
  await assertLoginLayout();
  const desktopLogin = await page.locator('.pf-v5-c-login__main').boundingBox();
  const desktopPanel = await page.locator('.dcn-resource-panel').boundingBox();
  assert(desktopLogin && desktopPanel && desktopPanel.x > desktopLogin.x + desktopLogin.width,
    `portal cards are not to the right of login: ${JSON.stringify({desktopLogin, desktopPanel})}`);
  await page.setViewportSize({width: 390, height: 844});
  await assertLoginLayout();
  const mobileLogin = await page.locator('.pf-v5-c-login__main').boundingBox();
  const mobilePanel = await page.locator('.dcn-resource-panel').boundingBox();
  assert(mobileLogin && mobilePanel && mobilePanel.y >= mobileLogin.y + mobileLogin.height,
    `portal cards are not below login on mobile: ${JSON.stringify({mobileLogin, mobilePanel})}`);
  const request = page.waitForRequest(r => r.url().startsWith('https://accounts.google.com/'));
  await google.click({noWaitAfter: true});
  const googleUrl = new URL((await request).url());
  assert.equal(
    googleUrl.searchParams.get('redirect_uri'),
    `${identityFrontend}/realms/dcn/broker/google/endpoint`,
    `Google callback escaped the Horizon identity path: ${googleUrl}`,
  );
  await page.waitForURL(url => url.hostname === 'accounts.google.com', {timeout: 30000});
  await page.locator('body').waitFor();
  assert(!/redirect_uri_mismatch|Error 400/i.test(await page.locator('body').innerText()), 'Google rejected the same-origin broker callback');
  assert.equal(failures.length, 0, failures.join('\n'));
  await browser.close();
  console.log('production-unified-login-browser-e2e-passed');
})().catch(e => { console.error(e); process.exit(1); });
