import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import test from "node:test";

const execFileAsync = promisify(execFile);
const previewer = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../preview.mjs");

test("independent resvg/pdf-lib exporter produces real PNG pages and PDF", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "slidethus-preview-"));
  const first = path.join(directory, "S-001.svg");
  const second = path.join(directory, "S-002.svg");
  const svg = (text, color) =>
    `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">` +
    `<rect width="1280" height="720" fill="${color}"/>` +
    `<text x="100" y="180" font-family="Arial" font-size="64">${text}</text></svg>`;
  await fs.writeFile(first, svg("First", "#F7F4ED"), "utf8");
  await fs.writeFile(second, svg("Second", "#FFFFFF"), "utf8");
  const inputs = path.join(directory, "inputs.json");
  await fs.writeFile(
    inputs,
    JSON.stringify([
      { slide_id: "S-001", path: first },
      { slide_id: "S-002", path: second },
    ]),
    "utf8",
  );
  const pngDir = path.join(directory, "png");
  const pdf = path.join(directory, "preview.pdf");
  const report = path.join(directory, "report.json");

  await execFileAsync(process.execPath, [
    previewer,
    "--inputs",
    inputs,
    "--png-dir",
    pngDir,
    "--pdf",
    pdf,
    "--report",
    report,
    "--generated-at",
    "2026-08-28T00:00:00Z",
  ]);

  const firstPng = await fs.readFile(path.join(pngDir, "S-001.png"));
  const secondPng = await fs.readFile(path.join(pngDir, "S-002.png"));
  const pdfBytes = await fs.readFile(pdf);
  const data = JSON.parse(await fs.readFile(report, "utf8"));
  assert.equal(firstPng.subarray(1, 4).toString("ascii"), "PNG");
  assert.equal(secondPng.subarray(1, 4).toString("ascii"), "PNG");
  assert.equal(pdfBytes.subarray(0, 4).toString("ascii"), "%PDF");
  assert.equal(data.slide_count, 2);
  assert.equal(data.outputs.length, 2);
});
