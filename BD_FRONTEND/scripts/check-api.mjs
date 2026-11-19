/**
 * Fails when the generated API client in `src/lib/api/` is out of date (task B2).
 *
 * Needed because the client must always match `BD_BACKEND/openapi.json`; `npm run check:api`
 * (and later `make check`) regenerates it and compares the files before and after, so a stale
 * or hand-edited client is caught instead of silently breaking the frontend. It compares file
 * contents, not git state, so it also works before the first commit.
 * Plain Node, no extra dependency, so it runs the same on Windows and Mac.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const GENERATED_DIR = "src/lib/api";

/** Returns a map of relative file path to content for every file under `dir` (empty if missing). */
function readTree(dir, base = dir) {
  const files = new Map();
  if (!existsSync(dir)) return files;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      for (const [path, content] of readTree(full, base)) files.set(path, content);
    } else {
      files.set(full.slice(base.length + 1), readFileSync(full, "utf8"));
    }
  }
  return files;
}

/** Lists the paths that were added, removed or changed between two trees. */
function differences(before, after) {
  const paths = new Set([...before.keys(), ...after.keys()]);
  return [...paths].filter((path) => before.get(path) !== after.get(path)).sort();
}

const before = readTree(GENERATED_DIR);
// Run npm's own JS entry point with the current Node, so no shell is needed (works on Windows
// and Mac). `npm_execpath` is set by npm whenever this file is started through `npm run`.
const npmCli = process.env.npm_execpath;
if (!npmCli) {
  console.error('Run this script through npm: "npm run check:api".');
  process.exit(2);
}
execFileSync(process.execPath, [npmCli, "run", "generate:api"], { stdio: "inherit" });
const changed = differences(before, readTree(GENERATED_DIR));

if (changed.length > 0) {
  console.error(
    `Generated API client was out of date (now regenerated). Review and commit:\n  ${changed.join("\n  ")}`,
  );
  process.exit(1);
}
console.log("Generated API client is up to date.");
