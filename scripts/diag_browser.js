// Capture the real network the AniKoto watch page makes to load the episode list
// and the stream — so we can replicate the working requests exactly.
const PW = 'C:/Users/Admin/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright-core';
const CHROME = 'C:/Users/Admin/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe';
const { chromium } = require(PW);

const TARGET = process.argv[2] || 'https://anikototv.to/watch/takopi-s-original-sin-ij2dl';
const PAT = /getinfo|episode|ajax\/server|ajax\/episode|\.m3u8|getSources|save_data|mapper|streamzone|seg-/i;

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const seen = [];
  page.on('response', async (resp) => {
    const url = resp.url();
    if (!PAT.test(url)) return;
    let body = '';
    try { body = (await resp.text()).slice(0, 220).replace(/\s+/g, ' '); } catch (e) { body = '<binary>'; }
    const req = resp.request();
    seen.push({
      method: req.method(), status: resp.status(), url: url.slice(0, 140),
      ct: (resp.headers()['content-type'] || '').slice(0, 40),
      xrw: req.headers()['x-requested-with'] || '-',
      ref: (req.headers()['referer'] || '-').slice(0, 60),
      body,
    });
  });
  try {
    await page.goto(TARGET, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(9000); // let the episode-list + player XHRs fire
    // Try to start playback so segment requests fire.
    try { await page.click('text=/play/i', { timeout: 3000 }); } catch {}
    await page.waitForTimeout(6000);
  } catch (e) { console.log('NAV ERROR', e.message); }
  console.log(`\n=== captured ${seen.length} relevant requests ===`);
  for (const h of seen) {
    console.log(`[${h.status}] ${h.method} xrw=${h.xrw} ${h.url}`);
    console.log(`        ct=${h.ct} ref=${h.ref}`);
    console.log(`        body=${h.body}`);
  }
  await browser.close();
})();
