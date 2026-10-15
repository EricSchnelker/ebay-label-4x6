// Screenshot of the real converter page (1280x800) after combining labels.
//   node store/shot_converter.js OUT.png LABEL.pdf [LABEL.pdf ...]
// Loads the unpacked extension into Playwright's Chromium, opens its page,
// uploads the given (synthetic) labels and waits for the "Done" status.
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const { chromium } = require("playwright");

const EXT = path.resolve(__dirname, "..", "extension");
const [out, ...labels] = process.argv.slice(2);

(async () => {
  const ctx = await chromium.launchPersistentContext(fs.mkdtempSync(path.join(os.tmpdir(), "shot-")), {
    headless: true,
    channel: "chromium",
    acceptDownloads: true,
    viewport: { width: 1280, height: 800 },
    colorScheme: "light",
    args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`],
  });
  try {
    let [sw] = ctx.serviceWorkers();
    if (!sw) sw = await ctx.waitForEvent("serviceworker", { timeout: 15000 });
    const extId = new URL(sw.url()).host;
    const page = await ctx.newPage();
    await page.goto(`chrome-extension://${extId}/convert.html`);
    const dl = page.waitForEvent("download");
    await page.setInputFiles("#files", labels);
    await dl;
    await page.waitForFunction(() => /^Done/.test(document.getElementById("status").textContent));
    await page.screenshot({ path: out });
  } finally {
    await ctx.close();
  }
})().catch((e) => { console.error("FAIL", e.message); process.exit(1); });
