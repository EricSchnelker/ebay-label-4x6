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
L.convert(inputs.map((p) => fs.readFileSync(p)))
  .then((bytes) => fs.writeFileSync(out, bytes))
  .catch((e) => { console.error("ERROR: " + e.message); process.exit(2); });
