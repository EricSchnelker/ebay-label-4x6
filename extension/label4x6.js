/*
 * label4x6.js -- eBay letter-sheet label -> upright 4x6 PDF, in the browser.
 *
 * Shared by the extension's background worker (importScripts), its converter
 * page (<script>) and the Node tests (require). Needs pdf-lib as the global
 * `PDFLib` (browser) or via require (Node).
 *
 * HOW (different from the desktop app, on purpose):
 * eBay's label PDF is structurally simple. Measured on real labels, the page
 * content is just
 *     q 0 -1 1 0 90 734.46 cm /Xf1 Do Q
 * and /Xf1 is a form XObject with /BBox [0 0 288 432] -- the WHOLE label,
 * already an upright 4x6 in its own coordinate space. eBay merely draws it
 * turned 90 degrees into a letter sheet. So instead of rendering the page and
 * hunting for ink (the desktop app's way, which needs PDFium), we lift that
 * form out and draw it unrotated on a fresh 288 x 432 page. Vector in, vector
 * out, no scaling: barcodes stay exactly as eBay generated them. And no
 * renderer means the extension ships only pdf-lib (~500 KB), not a 1 MB+
 * PDF.js build.
 *
 * SECURITY: the output is built from scratch and receives ONLY the label form
 * (deep-copied with its resources: fonts, images). Nothing else from the
 * source -- no annotations, page actions, JavaScript, forms or open actions --
 * can reach it. Inputs are capped (size, pages) and the content-stream parser
 * is a bounded, non-recursive tokenizer that gives up on anything unusual.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./vendor/pdf-lib.min.js"));
  } else {
    root.Label4x6 = factory(root.PDFLib);
  }
})(typeof self !== "undefined" ? self : globalThis, function (PDFLib) {
  "use strict";

  const {
    PDFDocument, PDFName, PDFDict, PDFArray, PDFNumber, PDFRawStream,
    PDFObjectCopier, decodePDFRawStream,
    pushGraphicsState, popGraphicsState, concatTransformationMatrix, drawObject,
  } = PDFLib;

  // 4 x 6 in at 72 pt/in, portrait -- what a 4x6 thermal printer feeds.
  const LABEL_W = 288;
  const LABEL_H = 432;
  // Slack when matching a form's /BBox to 4x6 (rounding in generators).
  const SIZE_SLACK = 3;

  // Untrusted-input caps; same values as the desktop app (see its README).
  const MAX_INPUT_BYTES = 25 * 1024 * 1024;
  const MAX_PAGES = 500;
  // A real eBay page stream is ~60 bytes. 1 MB of top-level content means
  // this is not an eBay label; stop before tokenizing it.
  const MAX_CONTENT_BYTES = 1024 * 1024;
  // ...and that check alone runs too late: decodePDFRawStream inflates the
  // whole stream first, so a 60 KB Flate "bomb" became 60 MB in memory before
  // being refused (caught by test_extension_refuses_content_bomb_*). Flate
  // expands at most ~1032:1, so capping the ENCODED size at 16 KB bounds the
  // inflate at ~16 MB. eBay's real page stream is ~60 bytes.
  const MAX_ENCODED_CONTENT = 16 * 1024;

  // ---------------------------------------------------------------- helpers

  function isPdf(bytes) {
    // "%PDF-" may legally sit anywhere in the first 1 KB.
    const head = new TextDecoder("latin1").decode(bytes.subarray(0, 1024));
    return head.includes("%PDF-");
  }

  function num(obj) {
    return obj instanceof PDFNumber ? obj.asNumber() : NaN;
  }

  /** Concatenated, decoded top-level content of a page (Uint8Array) or null. */
  function pageContent(doc, page) {
    const contents = page.node.Contents();
    if (!contents) return null;
    const streams = contents instanceof PDFArray
      ? contents.asArray().map((r) => doc.context.lookup(r))
      : [contents];
    const parts = [];
    let total = 0;
    for (const s of streams) {
      if (!(s instanceof PDFRawStream)) return null;
      if (s.contents.length > MAX_ENCODED_CONTENT) return null; // before decoding
      const bytes = decodePDFRawStream(s).decode();
      total += bytes.length + 1;
      if (total > MAX_CONTENT_BYTES) return null;
      parts.push(bytes, new Uint8Array([10]));
    }
    const out = new Uint8Array(total);
    let o = 0;
    for (const p of parts) { out.set(p, o); o += p.length; }
    return out;
  }

  /**
   * Find every form XObject the page's TOP-LEVEL content draws with Do.
   * Returns [{name}] -- the transform is not needed (we re-place the form
   * ourselves), only which forms are drawn.
   *
   * A deliberately small tokenizer: numbers, /names, operators. Strings,
   * arrays, dicts and comments are skipped; an inline image (BI) aborts,
   * because its binary payload cannot be tokenized safely and eBay's page
   * never has one. Linear time, no recursion.
   */
  function drawnForms(content) {
    const text = new TextDecoder("latin1").decode(content);
    const re = /%[^\r\n]*|\((?:\\.|[^\\)])*\)|<<|>>|\[|\]|<[0-9A-Fa-f\s]*>|\/[^\s\/\[\]()<>{}%]*|[+-]?(?:\d+\.?\d*|\.\d+)|[A-Za-z'"*]+/g;
    const found = [];
    let lastName = null;
    let m;
    while ((m = re.exec(text)) !== null) {
      const t = m[0];
      if (t[0] === "/") { lastName = t.slice(1); continue; }
      if (t === "BI") return null;
      if (t === "Do" && lastName) found.push({ name: lastName });
      if (/^[A-Za-z'"*]+$/.test(t)) lastName = null;
    }
    return found;
  }

  /** The page's 4x6 label form, or null: {ref, dict, bbox:[x0,y0,x1,y1]}. */
  function findLabelForm(doc, page) {
    const content = pageContent(doc, page);
    if (!content) return null;
    const forms = drawnForms(content);
    if (!forms) return null;
    const res = page.node.Resources();
    const xobjs = res && res.lookupMaybe(PDFName.of("XObject"), PDFDict);
    if (!xobjs) return null;
    for (const { name } of forms) {
      const ref = xobjs.get(PDFName.of(name));
      const obj = ref && doc.context.lookup(ref);
      if (!obj || !obj.dict) continue;
      const d = obj.dict;
      if (d.get(PDFName.of("Subtype")) !== PDFName.of("Form")) continue;
      // Only an identity (or absent) /Matrix: then the form's own space IS the
      // label's upright space. Anything else is not the eBay layout.
      const mtx = d.lookupMaybe(PDFName.of("Matrix"), PDFArray);
      if (mtx) {
        const v = mtx.asArray().map(num);
        const ident = [1, 0, 0, 1, 0, 0];
        if (v.length !== 6 || v.some((x, i) => Math.abs(x - ident[i]) > 1e-6)) continue;
      }
      const bb = d.lookupMaybe(PDFName.of("BBox"), PDFArray);
      if (!bb || bb.size() !== 4) continue;
      const [x0, y0, x1, y1] = bb.asArray().map(num);
      const w = Math.abs(x1 - x0), h = Math.abs(y1 - y0);
      if (Math.abs(w - LABEL_W) <= SIZE_SLACK && Math.abs(h - LABEL_H) <= SIZE_SLACK) {
        return { ref, bbox: [Math.min(x0, x1), Math.min(y0, y1)] };
      }
    }
    return null;
  }

  function isAlready4x6(page) {
    const { width, height } = page.getSize();
    return Math.abs(width - LABEL_W) <= SIZE_SLACK && Math.abs(height - LABEL_H) <= SIZE_SLACK;
  }

  // ---------------------------------------------------------------- public

  /**
   * Convert one or more label PDFs (array of Uint8Array/ArrayBuffer) into ONE
   * output PDF with one upright 4x6 page per label. Returns Uint8Array.
   * Throws Error with a human-readable message on anything unrecognised.
   */
  async function convert(inputs) {
    const out = await PDFDocument.create();
    out.setProducer("eBay Label 4x6");
    out.setCreator("eBay Label 4x6");
    let pages = 0;
    for (let i = 0; i < inputs.length; i++) {
      const bytes = inputs[i] instanceof Uint8Array ? inputs[i] : new Uint8Array(inputs[i]);
      if (bytes.length > MAX_INPUT_BYTES) throw new Error(`file ${i + 1}: too large (limit 25 MB)`);
      if (!isPdf(bytes)) throw new Error(`file ${i + 1}: not a PDF`);
      // updateMetadata:false = do not touch the source's info dict;
      // the source document object is discarded after copying anyway.
      const src = await PDFDocument.load(bytes, { updateMetadata: false });
      const srcPages = src.getPages();
      pages += srcPages.length;
      if (pages > MAX_PAGES) throw new Error(`too many pages (limit ${MAX_PAGES})`);
      const copier = PDFObjectCopier.for(src.context, out.context);
      for (const page of srcPages) {
        const label = findLabelForm(src, page);
        const dst = out.addPage([LABEL_W, LABEL_H]);
        if (label) {
          // Deep-copy ONLY the label form (+ its fonts/images) into the output.
          const formRef = out.context.register(copier.copy(src.context.lookup(label.ref)));
          const name = dst.node.newXObject("Label", formRef);
          // Shift the form's BBox origin to the page origin; no rotation, no scale.
          dst.pushOperators(
            pushGraphicsState(),
            concatTransformationMatrix(1, 0, 0, 1, -label.bbox[0], -label.bbox[1]),
            drawObject(name),
            popGraphicsState(),
          );
        } else if (isAlready4x6(page)) {
          // Already a 4x6 page (some other tool's output): re-embed its
          // CONTENT only -- embedPage builds a fresh form from the page's
          // content stream + resources, leaving annotations/actions behind.
          const [embedded] = await out.embedPdf(src, [src.getPages().indexOf(page)]);
          dst.drawPage(embedded, { x: 0, y: 0, width: LABEL_W, height: LABEL_H });
        } else {
          throw new Error(`file ${i + 1}: this does not look like an eBay label PDF ` +
                          "(no 4x6 label inside). Use the desktop app for other layouts.");
        }
        // pdf-lib gives every new page an empty /Annots []; drop it so the
        // output carries no annotation array at all (nothing to inject into).
        dst.node.delete(PDFName.of("Annots"));
      }
    }
    if (pages === 0) throw new Error("no pages to convert");
    return out.save();
  }

  /** "eBay_label_01-234.pdf" -> "eBay_label_01-234_4x6.pdf" */
  function outputName(name) {
    const base = name.replace(/^.*[\\/]/, "").replace(/\.pdf$/i, "");
    return `${base}_4x6.pdf`;
  }

  /** True for eBay's downloaded-label filenames we have not converted yet. */
  function isLabelName(name) {
    const base = name.replace(/^.*[\\/]/, "");
    return /^ebay_label.*\.pdf$/i.test(base) && !/_4x6\.pdf$/i.test(base);
  }

  return { convert, outputName, isLabelName, LABEL_W, LABEL_H, MAX_INPUT_BYTES, MAX_PAGES };
});
