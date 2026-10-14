/*
 * convert.js -- the converter page: drop / pick PDFs, get 4x6 PDFs back.
 *
 * Files are read with the File API (they never leave the browser) and the
 * results are handed back as blob: downloads. "Combine" makes one multi-page
 * PDF; otherwise each input becomes its own <name>_4x6.pdf.
 */
"use strict";

const drop = document.getElementById("drop");
const input = document.getElementById("files");
const combineBox = document.getElementById("combine");
const autoBox = document.getElementById("auto");
const statusEl = document.getElementById("status");

function say(msg, bad = false) {
  statusEl.textContent = msg; // textContent, never innerHTML: filenames are untrusted
  statusEl.className = bad ? "bad" : "";
}

function save(bytes, name) {
  const url = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Give the download a moment to start before releasing the blob.
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function stamp() {
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

async function handle(fileList) {
  // Sorted by name: eBay names files by order id, so this is order order.
  const files = [...fileList]
    .filter((f) => /\.pdf$/i.test(f.name) || f.type === "application/pdf")
    .sort((a, b) => a.name.localeCompare(b.name));
  if (!files.length) return say("No PDF files in that selection.", true);
  for (const f of files) {
    // Check the size BEFORE reading the file into memory.
    if (f.size > Label4x6.MAX_INPUT_BYTES) return say(`${f.name}: too large (limit 25 MB).`, true);
  }
  say(`Converting ${files.length} file(s)...`);
  try {
    const buffers = await Promise.all(files.map((f) => f.arrayBuffer()));
    if (files.length > 1 && combineBox.checked) {
      const out = await Label4x6.convert(buffers);
      save(out, `eBay_labels_${stamp()}_4x6.pdf`);
      say(`Done: ${files.length} labels combined into one PDF.`);
    } else {
      for (let i = 0; i < files.length; i++) {
        save(await Label4x6.convert([buffers[i]]), Label4x6.outputName(files[i].name));
      }
      say(`Done: ${files.length} label(s) converted.`);
    }
  } catch (e) {
    say(`Could not convert: ${e.message}`, true);
  }
}

drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  handle(e.dataTransfer.files);
});
input.addEventListener("change", () => { handle(input.files); input.value = ""; });

// Auto-convert toggle, stored in chrome.storage.sync (default on).
chrome.storage.sync.get("auto").then(({ auto = true }) => { autoBox.checked = auto; });
autoBox.addEventListener("change", () => chrome.storage.sync.set({ auto: autoBox.checked }));

// Last auto-convert attempt (written by background.js): when it ran, where the
// label came from (scheme + host only) and what happened. Makes a failure
// diagnosable without devtools.
chrome.storage.local.get("lastAuto").then(({ lastAuto }) => {
  const el = document.getElementById("lastAuto");
  if (!lastAuto) { el.textContent = "Auto-convert has not run yet."; return; }
  const when = new Date(lastAuto.at).toLocaleString();
  el.textContent = `Last auto-convert: ${when} -- ${lastAuto.scheme}: from ${lastAuto.host} -- ${lastAuto.outcome}`;
});
