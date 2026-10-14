/*
 * background.js -- auto-convert eBay labels the moment they finish downloading.
 *
 * Flow: a download completes -> its filename looks like eBay_label*.pdf ->
 * it came from an https://*.ebay.com URL -> fetch the same URL again (the
 * browser sends your eBay cookies, exactly as the original download did) ->
 * convert -> save <name>_4x6.pdf next to it in Downloads.
 *
 * WHY RE-FETCH: an extension cannot read a file from disk, even one it
 * watched being downloaded. Re-requesting the URL is the only way to get the
 * bytes. If that is impossible (the label was a blob: URL generated inside
 * the page, or the link expired), a notification offers the converter page,
 * where you drop the file instead.
 *
 * SECURITY:
 * - Auto mode acts ONLY on downloads whose URL is https and whose host is
 *   ebay.com or a subdomain. Any other site can name a download
 *   eBay_label.pdf, but it will not be auto-processed.
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

  const src = item.finalUrl || item.url;
  if (!isEbayUrl(src)) {
    notify("manual", "eBay Label 4x6",
      "This label can't be converted automatically. Click here, then drop the PDF on the converter.");
    return;
  }
  try {
    const resp = await fetch(src, { credentials: "include", redirect: "follow" });
    if (!resp.ok) throw new Error(`eBay answered ${resp.status}`);
    if (!isEbayUrl(resp.url)) throw new Error("redirected away from eBay");
    const len = Number(resp.headers.get("content-length") || 0);
    if (len > Label4x6.MAX_INPUT_BYTES) throw new Error("file too large");
    const bytes = new Uint8Array(await resp.arrayBuffer());
    const out = await Label4x6.convert([bytes]);
    await chrome.downloads.download({
      url: toDataUrl(out),
      // Basename only: downloads.download() resolves it inside the Downloads
      // folder and refuses paths that try to escape it.
      filename: Label4x6.outputName(item.filename),
      conflictAction: "uniquify",
    });
  } catch (e) {
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
