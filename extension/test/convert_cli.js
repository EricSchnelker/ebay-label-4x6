// Test harness (not shipped in the extension zip): run label4x6.js under Node.
//   node convert_cli.js OUT.pdf IN1.pdf [IN2.pdf ...]   -> combined output, exit 0
//   node convert_cli.js --names NAME...                 -> prints isLabelName/outputName as JSON
// On a conversion error prints "ERROR: <message>" to stderr and exits 2.
"use strict";
const fs = require("fs");
const path = require("path");
const L = require(path.join(__dirname, "..", "label4x6.js"));

const args = process.argv.slice(2);
if (args[0] === "--names") {
  console.log(JSON.stringify(args.slice(1).map((n) => [L.isLabelName(n), L.outputName(n)])));
  process.exit(0);
}
const [out, ...inputs] = args;
// Always report this process's own peak memory (KB) on stderr, so tests can
// prove a hostile input was refused WITHOUT being inflated. On Linux this
// reads VmHWM: getrusage's maxrss (process.resourceUsage().maxRSS) SURVIVES
// exec, so a Node launched by a big Python test process would inherit the
// parent's peak and hide the very growth we are measuring.
function peakKb() {
  try {
    const m = /VmHWM:\s+(\d+)\s+kB/.exec(fs.readFileSync("/proc/self/status", "utf8"));
    if (m) return Number(m[1]);
  } catch (_) { /* not Linux */ }
  return process.resourceUsage().maxRSS;
}
const reportRss = () => console.error("maxrss_kb=" + peakKb());
L.convert(inputs.map((p) => fs.readFileSync(p)))
  .then((bytes) => { fs.writeFileSync(out, bytes); reportRss(); })
  .catch((e) => { console.error("ERROR: " + e.message); reportRss(); process.exit(2); });
