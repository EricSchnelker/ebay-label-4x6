// End-to-end check in a real Chromium with the extension loaded (not shipped).
//   node extension/test/e2e.js FIXTURE.pdf OUTDIR
// 1. extension loads, background worker starts
// 2. converter page: upload two labels with "combine" -> one download, 2 pages
// 3. auto mode: the worker's real download handler, fed a fake download
//    record (eBay URL vs non-eBay URL) -> converts + saves only the eBay one
// Prints one "ok <step>" line per step; exits non-zero on the first failure.
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const { chromium } = require("playwright");

const EXT = path.resolve(__dirname, "..");
const [fixture, outDir] = process.argv.slice(2);
const label = fs.readFileSync(fixture);

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "e4x6-"));
  const ctx = await chromium.launchPersistentContext(profile, {
    headless: true,
    channel: "chromium", // new headless: supports extensions
    acceptDownloads: true,
    downloadsPath: outDir,
    args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`],
  });
  try {
    // 1. background worker up
    let [sw] = ctx.serviceWorkers();
    if (!sw) sw = await ctx.waitForEvent("serviceworker", { timeout: 15000 });
    const extId = new URL(sw.url()).host;
    console.log("ok extension loaded", extId);

    // 2. converter page, combine two
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    await page.goto(`chrome-extension://${extId}/convert.html`);
    const a = path.join(outDir, "eBay_label_a.pdf"), b = path.join(outDir, "eBay_label_b.pdf");
    fs.writeFileSync(a, label); fs.writeFileSync(b, label);
    const dl = page.waitForEvent("download", { timeout: 20000 });
    await page.setInputFiles("#files", [a, b]);
    const d = await dl;
    const combined = path.join(outDir, "page_combined.pdf");
    await d.saveAs(combined);
    if (!/^eBay_labels_\d{8}-\d{6}_4x6\.pdf$/.test(d.suggestedFilename())) throw new Error("bad name " + d.suggestedFilename());
    if (errors.length) throw new Error("page errors: " + errors.join(" | "));
    console.log("ok converter page", d.suggestedFilename());

    // 3. auto mode. Playwright cannot drive this part fully naturally: it
    // renames downloads to GUIDs (real Chrome keeps eBay_label_*.pdf) and its
    // request routing does not reach an extension worker's own fetch(). So we
    // call the worker's REAL handler, stubbing only the two inputs it reads
    // -- the download record and the network re-fetch -- inside the worker.
    // Everything after that (eBay-host check, convert, chrome.downloads
    // save) is the shipped code. Not covered here: eBay's real URL + cookies.
    const labelB64 = label.toString("base64");
    const result = await sw.evaluate(async (b64) => {
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const realSearch = chrome.downloads.search, realFetch = self.fetch;
      const fetched = [];
      const fake = (url) => async () => [{ id: 4242, filename: "/dl/eBay_label_e2e.pdf", url, finalUrl: url }];
      // Only http(s) counts: chrome.notifications also fetch()es its icon.
      self.fetch = async (u) => {
        if (/^https?:/.test(String(u))) fetched.push(String(u));
        if (!/^https?:/.test(String(u))) return realFetch(u);
        // A constructed Response has url ""; a real fetch reports where it
        // landed, which the extension checks (redirect-away guard).
        const resp = new Response(bytes, { status: 200 });
        Object.defineProperty(resp, "url", { value: String(u) });
        return resp;
      };
      try {
        // negative: same filename, NOT from eBay -> must not fetch or save
        chrome.downloads.search = fake("https://evil.example/eBay_label_e2e.pdf");
        await handleComplete(4242);
        const afterEvil = fetched.length;
        // positive: from eBay -> fetch, convert, save
        chrome.downloads.search = fake("https://www.ebay.com/ship/label.pdf");
        await handleComplete(4242);
        return { afterEvil, fetched };
      } finally {
        chrome.downloads.search = realSearch;
        self.fetch = realFetch;
      }
    }, labelB64);
    if (result.afterEvil !== 0) throw new Error("fetched a non-eBay URL: " + result.fetched);
    if (result.fetched.length !== 1) throw new Error("eBay label not fetched: " + JSON.stringify(result));
    console.log("ok auto-convert ignores non-eBay downloads");
    const deadline = Date.now() + 20000;
    let item = null;
    while (Date.now() < deadline && !item) {
      item = await sw.evaluate(async (id) => {
        // byExtensionId is a result field, not a query filter: filter here.
        const all = await chrome.downloads.search({});
        return all.find((x) => x.byExtensionId === id && x.state === "complete" && x.url.startsWith("data:")) || null;
      }, extId);
      if (!item) await new Promise((r) => setTimeout(r, 500));
    }
    if (!item) throw new Error("auto-convert produced no download");
    fs.copyFileSync(item.filename, path.join(outDir, "auto_out.pdf"));
    console.log("ok auto-convert saved a converted copy");
  } finally {
    await ctx.close();
  }
})().catch((e) => { console.error("FAIL", e.message); process.exit(1); });
