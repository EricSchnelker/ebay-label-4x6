/*
 * background.js -- auto-convert eBay labels the moment they finish downloading.
 *
 * Flow: a download completes -> its filename looks like eBay_label*.pdf ->
 * it came from an https://*.ebay.com URL -> fetch the same URL again (the
 * browser sends your eBay cookies, exactly as the original download did) ->
 * convert -> save <name>_4x6.pdf next to it in Downloads.
 *
 * WHY RE-FETCH: an extension cannot read a file from disk, even one it
 * watched being downloaded, so it re-reads the label from where it came from:
 *   https://*.ebay.com/...      -> fetched again (your eBay cookies apply)
 *   blob:https://*.ebay.com/... -> THE REAL EBAY CASE (found on a live label,
 *        2026-10-14): the print page builds the PDF in-page and Chrome
 *        downloads it from a blob: URL. A blob belongs to the page that made
 *        it, so the worker cannot fetch it; it is read through that eBay tab
 *        with chrome.scripting (needs the "scripting" permission).
 *   data:application/pdf...     -> decoded directly, only when the download's
 *        referrer is an eBay page.
 * If none works (tab closed, link expired), a notification offers the
 * converter page, where you drop the file instead. Every attempt's outcome
 * (scheme + host + result, never the full URL) is kept in
 * chrome.storage.local "lastAuto" and shown on the converter page.
 *
 * SECURITY:
 * - Auto mode acts ONLY on labels from an https eBay origin (ebay.com or a
 *   subdomain): the URL itself, the origin inside a blob: URL, or the
 *   referrer of a data: URL. Any other site can name a download
 *   eBay_label.pdf, but it will not be auto-processed.
 * - A blob: is read only from a frame whose origin IS the blob's origin,
 *   and only in tabs the eBay host permission already covers.
 * - host_permissions are limited to https://*.ebay.com/* -- the extension
 *   cannot read any other site.
 * - Nothing is sent anywhere: the only network request is the re-fetch from
 *   eBay itself. Conversion runs locally (label4x6.js + pdf-lib).
 */
importScripts("vendor/pdf-lib.min.js", "label4x6.js");

const CONVERTER_PAGE = "convert.html";

/** Is this an eBay-hosted https URL? Exact host check, not substring. */
function isEbayUrl(u) {
  try {
    const url = new URL(u);
    return url.protocol === "https:" &&
      (url.hostname === "ebay.com" || url.hostname.endsWith(".ebay.com"));
  } catch {
    return false;
  }
}

/** The origin a download really came from, or null if not an eBay origin. */
function ebayOriginOf(item) {
  const src = item.finalUrl || item.url || "";
  try {
    if (src.startsWith("blob:")) {
      const inner = new URL(src.slice(5)).origin; // blob:<origin>/<uuid>
      return isEbayUrl(inner) ? inner : null;
    }
    if (src.startsWith("data:")) {
      return item.referrer && isEbayUrl(item.referrer) ? new URL(item.referrer).origin : null;
    }
    return isEbayUrl(src) ? new URL(src).origin : null;
  } catch {
    return null;
  }
}

/** Record what auto mode did, without the full URL (it can carry tokens). */
async function remember(item, outcome) {
  const src = item.finalUrl || item.url || "";
  let scheme = "?", host = "?";
  try {
    scheme = src.split(":", 1)[0];
    const u = scheme === "blob" ? new URL(src.slice(5)) : new URL(src);
    host = scheme === "data" ? (item.referrer ? new URL(item.referrer).host : "-") : u.host;
  } catch { /* keep "?" */ }
  await chrome.storage.local.set({ lastAuto: { at: new Date().toISOString(), scheme, host, outcome } });
}

function fromBase64(b64) {
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

/**
 * Read a page-made blob: through the eBay tab that owns it. Runs in every
 * frame of every eBay tab; a frame whose origin is not the blob's returns
 * nothing (the browser would refuse the fetch anyway).
 */
async function readBlobViaTab(src, origin) {
  const tabs = await chrome.tabs.query({ url: ["https://ebay.com/*", "https://*.ebay.com/*"] });
  for (const tab of tabs) {
    let results = [];
    try {
      results = await chrome.scripting.executeScript({
        target: { tabId: tab.id, allFrames: true },
        args: [src, origin, Label4x6.MAX_INPUT_BYTES],
        func: async (blobUrl, wantOrigin, max) => {
          if (location.origin !== wantOrigin) return null;
          try {
            const b = await (await fetch(blobUrl)).blob();
            if (b.size > max) return { error: "file too large" };
            const bytes = new Uint8Array(await b.arrayBuffer());
            let bin = "";
            for (let i = 0; i < bytes.length; i += 0x8000) {
              bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
            }
            return { b64: btoa(bin) };
          } catch (e) {
            return null; // not this frame's blob, or already revoked
          }
        },
      });
    } catch {
      continue; // tab gone, or a page scripting is not allowed on
    }
    for (const r of results) {
      if (r && r.result && r.result.error) throw new Error(r.result.error);
      if (r && r.result && r.result.b64) return fromBase64(r.result.b64);
    }
  }
  throw new Error("the eBay tab that made this label is gone or no longer has it");
}

/** Bytes of the downloaded label, by where it came from (see top). */
async function getLabelBytes(item, origin) {
  const src = item.finalUrl || item.url;
  if (src.startsWith("blob:")) return readBlobViaTab(src, origin);
  if (src.startsWith("data:")) {
    const resp = await fetch(src);
    return new Uint8Array(await resp.arrayBuffer());
  }
  const resp = await fetch(src, { credentials: "include", redirect: "follow" });
  if (!resp.ok) throw new Error(`eBay answered ${resp.status}`);
  if (!isEbayUrl(resp.url)) throw new Error("redirected away from eBay");
  const len = Number(resp.headers.get("content-length") || 0);
  if (len > Label4x6.MAX_INPUT_BYTES) throw new Error("file too large");
  return new Uint8Array(await resp.arrayBuffer());
}

/** Uint8Array -> data: URL. (Service workers have no URL.createObjectURL.) */
function toDataUrl(bytes) {
  let bin = "";
  const CHUNK = 0x8000; // stay under the argument limit of fromCharCode.apply
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return "data:application/pdf;base64," + btoa(bin);
}

function notify(id, title, message) {
  chrome.notifications.create(id, {
    type: "basic", iconUrl: "icons/128.png", title, message,
  });
}

async function autoEnabled() {
  const { auto = true } = await chrome.storage.sync.get("auto");
  return auto;
}

async function handleComplete(id) {
  const [item] = await chrome.downloads.search({ id });
  if (!item || item.byExtensionId === chrome.runtime.id) return; // never re-process our own output
  if (!Label4x6.isLabelName(item.filename)) return;
  if (!(await autoEnabled())) return;

  const origin = ebayOriginOf(item);
  if (!origin) {
    await remember(item, "skipped: not from an eBay origin");
    notify("manual", "eBay Label 4x6",
      "This label can't be converted automatically. Click here, then drop the PDF on the converter.");
    return;
  }
  try {
    const bytes = await getLabelBytes(item, origin);
    if (bytes.length > Label4x6.MAX_INPUT_BYTES) throw new Error("file too large");
    const out = await Label4x6.convert([bytes]);
    await chrome.downloads.download({
      url: toDataUrl(out),
      // Basename only: downloads.download() resolves it inside the Downloads
      // folder and refuses paths that try to escape it.
      filename: Label4x6.outputName(item.filename),
      conflictAction: "uniquify",
    });
    await remember(item, "converted");
  } catch (e) {
    await remember(item, "failed: " + e.message);
    notify("manual", "eBay Label 4x6",
      `Auto-convert failed (${e.message}). Click here, then drop the PDF on the converter.`);
  }
}

chrome.downloads.onChanged.addListener((delta) => {
  if (delta.state && delta.state.current === "complete") {
    handleComplete(delta.id).catch((e) => console.error("eBay Label 4x6:", e));
  }
});

chrome.notifications.onClicked.addListener(() => {
  chrome.tabs.create({ url: CONVERTER_PAGE });
});

chrome.action.onClicked.addListener(() => {
  chrome.tabs.create({ url: CONVERTER_PAGE });
});
