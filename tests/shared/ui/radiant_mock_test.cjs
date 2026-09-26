"use strict";
const assert = require("node:assert/strict"), http = require("node:http"), fs = require("node:fs"), path = require("node:path");
const { chromium } = require("playwright");
const root = path.resolve(__dirname, "../../../src/WraithXCOD/WraithXCOD/ui");
const server = http.createServer((req, res) => {
  const name = new URL(req.url, "http://localhost").pathname.slice(1) || "index.html", file = path.resolve(root, name);
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  fs.readFile(file, (err, bytes) => { if (err) return res.writeHead(404).end(); res.setHeader("Content-Type", ({ ".js": "application/javascript", ".css": "text/css", ".html": "text/html" })[path.extname(file)] || "application/octet-stream"); res.end(bytes); });
});
(async () => {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const page = await browser.newPage(), errors = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.locator('[data-page="tools"]').click();
    const button = page.locator('[data-tool="brushes"]');
    assert(await button.isDisabled(), "unloaded map cannot export brushes");
    for (const id of ["black_ops_4", "black_ops_cw"]) {
      await page.evaluate(id => GreyhoundMock.receive("state", { loaded: true, game: { id, name: id }, total: 1 }), id);
      await page.waitForFunction(() => !document.querySelector('[data-tool="brushes"]').disabled);
      assert.equal(await button.locator("..").locator('[data-need="bo4cw"]').textContent(), "");
    }
    await page.evaluate(() => GreyhoundMock.receive("state", { loaded: true, game: { id: "black_ops_4", name: "Black Ops 4" }, busy: true }));
    await page.waitForFunction(() => document.querySelector('[data-tool="brushes"]').disabled);
    await page.evaluate(() => GreyhoundMock.receive("state", { loaded: true, game: { id: "black_ops_4", name: "Black Ops 4", file: true } }));
    assert(await button.isDisabled(), "an asset file is not a live map");
    await page.evaluate(() => GreyhoundMock.receive("state", { loaded: true, game: { id: "black_ops_3", name: "Black Ops 3" } }));
    await page.waitForFunction(() => document.querySelector('[data-need="bo4cw"]').textContent.includes("Load"));
    assert(await button.isDisabled(), "unsupported game cannot use this reader");
    await page.evaluate(() => GreyhoundMock.receive("job", { title: "Radiant brushes", state: "failed", status: "Brush conversion failed", path: "C:\\export\\diagnostics" }));
    await page.waitForFunction(() => document.querySelector("#job").classList.contains("failed"));
    assert.equal(await page.locator("#jobState").textContent(), "Needs a look");
    assert(!(await page.locator("#job").evaluate(el => el.classList.contains("done"))));
    assert.equal(await page.locator("#jobOpen").getAttribute("data-path"), "C:\\export\\diagnostics");
    assert.deepEqual(errors, []);
    console.log("Radiant UI: BO4/CW availability, file/busy guards and failed-job display passed");
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; server.close(); });
