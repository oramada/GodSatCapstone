// Records what the built window was made from, as scripts/studio/build_wasm.py does for the
// compute core: the SHA-256 of every source file and of the bundle's own files. The service
// test (tests/unit/test_studio.py) recomputes the source hashes, so a source change that
// wasn't rebuilt fails CI instead of shipping a stale web/studio/app.
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../..", import.meta.url));
const out = join(root, "web/studio/app");

function files(dir, keep) {
  const found = [];
  for (const name of readdirSync(dir).sort()) {
    if (name.startsWith(".")) continue; // .DS_Store and friends never reach a checkout
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name !== "node_modules") found.push(...files(path, keep));
    } else if (keep(path)) found.push(path);
  }
  return found;
}

const sha = (path) => createHash("sha256").update(readFileSync(path)).digest("hex");
const rel = (path) => relative(root, path).split(sep).join("/");
const sources = [
  ...files(join(root, "web/ui/src"), (p) => /\.(tsx?|css)$/.test(p) && !/\.test\.tsx?$/.test(p)),
  ...files(join(root, "web/ui/public"), () => true),
  ...files(join(root, "web/ui/vendor/sam-design-system"), () => true),
  ...files(join(root, "web/studio"), (p) => /\.js$/.test(p) && !p.startsWith(out + sep) && !p.includes(`${sep}vendor${sep}`)),
  ...["web/ui/index.html", "web/ui/package.json", "web/ui/bun.lock", "web/ui/vite.config.ts", "web/ui/tsconfig.json"].map((p) => join(root, p)),
];

const bundle = files(out, (p) => !p.endsWith(`${sep}build.json`));
const metadata = {
  tool: "vite",
  source_sha256: Object.fromEntries(sources.map((p) => [rel(p), sha(p)])),
  bundle_sha256: Object.fromEntries(bundle.map((p) => [rel(p), sha(p)])),
};
writeFileSync(join(out, "build.json"), JSON.stringify(metadata, null, 2) + "\n");
console.log(`stamped ${sources.length} sources, ${bundle.length} bundle files`);
