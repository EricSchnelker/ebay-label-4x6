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

    // 4. The REAL eBay flow (found 2026-10-14 on a live label): the print page
    // builds the PDF in-page and Chrome downloads it from a blob: URL such as
    // blob:https://www.ebay.com/<uuid>. The extension's page hook copies the
    // label the moment the page creates that blob, so the conversion must work
    // EVEN AFTER THE EBAY TAB IS CLOSED (Eric: needing the tab open "defeats
    // the point"). Build exactly that, then close the tab before the download
    // is processed.
    await ctx.route("https://www.ebay.com/**", (route) =>
      route.fulfill({ status: 200, contentType: "text/html", body: "<title>print</title>" }));
    const ebay = await ctx.newPage();
    await ebay.goto("https://www.ebay.com/ship/single/print/e2e");
    const blobUrl = await ebay.evaluate((b64) => {
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      return URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
    }, labelB64);
    if (!blobUrl.startsWith("blob:https://www.ebay.com/")) throw new Error("bad blob url " + blobUrl);
    // Give the hook -> bridge -> worker hand-off a moment, then close the tab.
    await new Promise((r) => setTimeout(r, 1500));
    await ebay.close();
    const before = await sw.evaluate(async (id) =>
      (await chrome.downloads.search({})).filter((x) => x.byExtensionId === id).length, extId);
    await sw.evaluate(async (u) => {
      const realSearch = chrome.downloads.search;
      chrome.downloads.search = async () => [{ id: 4343, filename: "/dl/eBay_label_blob.pdf", url: u, finalUrl: u }];
      try { await handleComplete(4343); } finally { chrome.downloads.search = realSearch; }
    }, blobUrl);
    let blobItem = null;
    const deadline2 = Date.now() + 20000;
    while (Date.now() < deadline2 && !blobItem) {
      blobItem = await sw.evaluate(async ({ id, before }) => {
        const mine = (await chrome.downloads.search({})).filter((x) => x.byExtensionId === id && x.state === "complete");
        return mine.length > before ? mine[mine.length - 1] : null;
      }, { id: extId, before });
      if (!blobItem) await new Promise((r) => setTimeout(r, 500));
    }
    if (!blobItem) {
      const last = await sw.evaluate(async () => (await chrome.storage.local.get("lastAuto")).lastAuto || null);
      throw new Error("blob: label not auto-converted; lastAuto=" + JSON.stringify(last));
    }
    fs.copyFileSync(blobItem.filename, path.join(outDir, "auto_blob_out.pdf"));
    console.log("ok auto-convert converts a blob: label after its eBay tab is closed");

    // 5. A blob: from any other site must NOT be read, even with the right filename.
    await ctx.route("https://evil.example/**", (route) =>
      route.fulfill({ status: 200, contentType: "text/html", body: "<title>x</title>" }));
    const evil = await ctx.newPage();
    await evil.goto("https://evil.example/");
    const evilBlob = await evil.evaluate((b64) => URL.createObjectURL(new Blob([Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))])), labelB64);
    const countBefore = await sw.evaluate(async (id) =>
      (await chrome.downloads.search({})).filter((x) => x.byExtensionId === id).length, extId);
    await sw.evaluate(async (u) => {
      const realSearch = chrome.downloads.search;
      chrome.downloads.search = async () => [{ id: 4444, filename: "/dl/eBay_label_evil.pdf", url: u, finalUrl: u }];
      try { await handleComplete(4444); } finally { chrome.downloads.search = realSearch; }
    }, evilBlob);
    await new Promise((r) => setTimeout(r, 1500));
    const countAfter = await sw.evaluate(async (id) =>
      (await chrome.downloads.search({})).filter((x) => x.byExtensionId === id).length, extId);
    if (countAfter !== countBefore) throw new Error("converted a blob: from a non-eBay site");
    console.log("ok auto-convert ignores blob: labels from other sites");
  } finally {
    await ctx.close();
  }
})().catch((e) => { console.error("FAIL", e.message); process.exit(1); });
