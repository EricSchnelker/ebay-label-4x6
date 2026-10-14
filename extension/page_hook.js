/*
 * page_hook.js -- runs IN eBay's page (MAIN world, document_start), and only
 * on https://*.ebay.com.
 *
 * WHY: eBay's print page builds the label PDF in the page and hands Chrome a
 * blob: URL. A blob lives only as long as its page, so by the time a download
 * finishes the tab may be closed and the bytes gone -- and needing the tab
 * kept open "defeats the point" of an auto-converter. So we copy the label at
 * the moment it is CREATED: wrap URL.createObjectURL, and when the page makes
 * a blob URL for a PDF, pass (url, blob) to our isolated-world bridge
 * (page_bridge.js), which hands it to the background worker. The worker only
 * USES the copy if that exact blob URL is later downloaded under an
 * eBay_label*.pdf name; otherwise it is simply discarded.
 *
 * Kept deliberately tiny and transparent: the original createObjectURL is
 * always called and its result returned unchanged, nothing on the page is
 * altered, and any error in our code is swallowed so it can never break eBay.
 */
(() => {
  "use strict";
  const original = URL.createObjectURL;
  // Same 25 MB cap as the converter: a bigger "PDF" is not a label.
  const MAX = 25 * 1024 * 1024;
  URL.createObjectURL = function (obj) {
    const url = original.apply(this, arguments);
    try {
      if (obj instanceof Blob && obj.size > 0 && obj.size <= MAX &&
          (obj.type === "application/pdf" || obj.type === "" || obj.type === "application/octet-stream")) {
        // Same-window, same-origin hand-off to page_bridge.js. The bridge
        // re-checks the %PDF header itself; nothing here is trusted.
        window.postMessage({ __ebayLabel4x6: 1, url, blob: obj }, location.origin);
      }
    } catch (e) { /* never break the page */ }
    return url;
  };
})();
