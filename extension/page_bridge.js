/*
 * page_bridge.js -- the extension's ISOLATED-world content script on
 * https://*.ebay.com. Receives (blob URL, blob) from page_hook.js and passes a
 * copy of the bytes to the background worker, which keeps it only until a
 * download of that same blob URL completes (see background.js "captured").
 *
 * Trust: anything from the page is data, never instructions. A message is
 * taken only if it comes from THIS window, names a blob: URL of THIS page's
 * own origin, is within the size cap and actually starts with %PDF-.
 */
(() => {
  "use strict";
  const MAX = 25 * 1024 * 1024;
  window.addEventListener("message", async (event) => {
    const d = event.data;
    if (event.source !== window || !d || d.__ebayLabel4x6 !== 1) return;
    if (typeof d.url !== "string" || !d.url.startsWith("blob:" + location.origin + "/")) return;
    if (!(d.blob instanceof Blob) || d.blob.size === 0 || d.blob.size > MAX) return;
    try {
      const bytes = new Uint8Array(await d.blob.arrayBuffer());
      const head = new TextDecoder("latin1").decode(bytes.subarray(0, 1024));
      if (!head.includes("%PDF-")) return; // not a PDF: ignore quietly
      let bin = "";
      for (let i = 0; i < bytes.length; i += 0x8000) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      }
      chrome.runtime.sendMessage({ type: "label-blob", url: d.url, b64: btoa(bin) });
    } catch (e) { /* worker asleep or page navigating: the tab path remains */ }
  });
})();
