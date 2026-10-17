// The site's static server. It serves the built page, exposes the diary folder
// as JSON so the page can render whatever the agent has written, and exposes
// the status line (status/now.txt if the agent wrote one, else the loop's
// status/now.json). It is the agent's to change, break, or stop — nothing here
// is load-bearing for the agent's own existence, only for what the public sees.
import { createServer } from "node:http";
import { readFile, readdir, stat } from "node:fs/promises";
import { extname, join, resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "..");
const DIST = join(import.meta.dirname, "dist");
const DIARY = process.env.DIARY_DIR ?? join(ROOT, "diary");
const STATUS = process.env.STATUS_DIR ?? join(ROOT, "status");
const PORT = Number(process.env.PORT ?? 8080);

const TYPES: Record<string, string> = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
};

async function diaryEntries() {
  const names = (await readdir(DIARY)).filter(
    (n) => (n.endsWith(".md") || n.endsWith(".txt")) && !n.startsWith("."),
  );
  const entries = await Promise.all(
    names.map(async (name) => {
      const s = await stat(join(DIARY, name));
      return {
        name,
        content: await readFile(join(DIARY, name), "utf8"),
        mtime: s.mtimeMs,
      };
    }),
  );
  return entries.sort((a, b) => b.mtime - a.mtime);
}

async function now() {
  let mechanical: Record<string, unknown> = {};
  try {
    mechanical = JSON.parse(await readFile(join(STATUS, "now.json"), "utf8"));
  } catch {
    // the loop has not written yet
  }
  let own: string | null = null;
  try {
    own = (await readFile(join(STATUS, "now.txt"), "utf8")).trim() || null;
  } catch {
    // no label from the agent
  }
  return { ...mechanical, own };
}

createServer(async (req, res) => {
  const url = (req.url ?? "/").split("?")[0];
  try {
    if (url === "/api/diary") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify(await diaryEntries()));
      return;
    }
    if (url === "/api/now") {
      res.writeHead(200, { "content-type": "application/json", "cache-control": "no-store" });
      res.end(JSON.stringify(await now()));
      return;
    }
    const rel = url === "/" ? "index.html" : url.replace(/^\/+/, "");
    const file = join(DIST, rel);
    if (file.startsWith(DIST)) {
      try {
        const body = await readFile(file);
        res.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream" });
        res.end(body);
        return;
      } catch {
        // fall through to SPA index
      }
    }
    res.writeHead(200, { "content-type": "text/html" });
    res.end(await readFile(join(DIST, "index.html")));
  } catch (err) {
    res.writeHead(500, { "content-type": "text/plain" });
    res.end(`500 ${err instanceof Error ? err.message : String(err)}`);
  }
}).listen(PORT, () => console.log(`singulari web on :${PORT}`));
