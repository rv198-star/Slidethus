import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import test from "node:test";
import JSZip from "jszip";

const execFileAsync = promisify(execFile);
const renderer = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../render.mjs");

function style(overrides = {}) {
  return {
    font_family: "Arial",
    font_size: 20,
    font_weight: 400,
    line_height: 1.2,
    color: "#17233C",
    fill: null,
    border_color: null,
    border_width: 0,
    ...overrides,
  };
}

function region(index, contentType, content, geometry, extra = {}) {
  return {
    region_id: `REG-S001-${String(index).padStart(2, "0")}`,
    block_id: `BLK-S001-${String(index).padStart(2, "0")}`,
    semantic_role: contentType === "text" ? "body" : contentType,
    content_type: contentType,
    priority: index === 1 ? "primary" : "secondary",
    content,
    claim_mode: ["chart", "table"].includes(contentType) ? "fact" : "label",
    evidence_qualification: null,
    evidence_ids: [],
    asset_refs: [],
    x: geometry[0],
    y: geometry[1],
    w: geometry[2],
    h: geometry[3],
    z: 1,
    align: "left",
    valign: "top",
    overflow_strategy: "fail",
    style: style(contentType === "table" || contentType === "chart" ? {
      fill: "#FFFFFF",
      border_color: "#D8D2C6",
      border_width: 1,
    } : {}),
    ...extra,
  };
}

function fixture(includeDiagram) {
  const regions = [
    region(1, "text", "Native headline and body", [72, 60, 1136, 70]),
    region(2, "table", { headers: ["A", "B"], rows: [[1, 2], [3, 4]] }, [72, 170, 480, 260]),
    region(
      3,
      "chart",
      {
        type: "bar",
        categories: ["A", "B"],
        series: [{ name: "Series", values: [3, 5] }],
      },
      [620, 160, 560, 300],
    ),
  ];
  if (includeDiagram) {
    regions.push(region(4, "diagram", ["Data", "Tools", "Rules"], [160, 500, 960, 140]));
  }
  return {
    schema_version: "0.1.0",
    project_id: "TST",
    deck_id: "DECK-TST",
    ir_id: "RIR-0000000000000000",
    generated_at: "2026-08-28T00:00:00Z",
    input_artifacts: [],
    canvas: { width: 1280, height: 720, background: "#F7F4ED" },
    safe_area: { top: 48, right: 56, bottom: 44, left: 56 },
    slides: [
      {
        slide_id: "S-001",
        ordinal: 1,
        layout_family: "architecture",
        decorations: [
          {
            decoration_id: "DEC-S001-01",
            kind: "rect",
            x: 0,
            y: 0,
            w: 12,
            h: 720,
            fill: "#D96C4B",
            stroke: null,
            z: 0,
          },
        ],
        regions,
      },
    ],
    fonts: ["Arial"],
    asset_ids: [],
    warnings: [],
  };
}

async function runRenderer(directory, mode, ir) {
  const input = path.join(directory, `${mode}-ir.json`);
  const output = path.join(directory, `${mode}.pptx`);
  const report = path.join(directory, `${mode}-report.json`);
  await fs.writeFile(input, `${JSON.stringify(ir, null, 2)}\n`, "utf8");
  await execFileAsync(process.execPath, [
    renderer,
    "--mode",
    mode,
    "--input",
    input,
    "--output",
    output,
    "--report",
    report,
    "--target-editability",
    mode === "native" ? "E3" : "E2",
  ]);
  return {
    output,
    report: JSON.parse(await fs.readFile(report, "utf8")),
    zip: await JSZip.loadAsync(await fs.readFile(output)),
  };
}

test("native backend emits editable text, table and chart objects", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "slidethus-native-"));
  const rendered = await runRenderer(directory, "native", fixture(false));

  assert.equal(rendered.report.measured_editability_level, "E3");
  assert.equal(rendered.report.object_counts.table, 1);
  assert.equal(rendered.report.object_counts.chart, 1);
  assert.equal(rendered.report.object_counts.embedded_svg, 0);
  assert.ok(rendered.zip.file("ppt/slides/slide1.xml"));
  assert.ok(rendered.zip.file("ppt/charts/chart1.xml"));
  const media = Object.keys(rendered.zip.files).filter(
    (name) => name.startsWith("ppt/media/") && !name.endsWith("/"),
  );
  assert.equal(media.length, 0);
});

test("hybrid backend embeds complex SVG while retaining native text/table/chart", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "slidethus-hybrid-"));
  const rendered = await runRenderer(directory, "hybrid", fixture(true));

  assert.equal(rendered.report.measured_editability_level, "E2");
  assert.equal(rendered.report.object_counts.table, 1);
  assert.equal(rendered.report.object_counts.chart, 1);
  assert.equal(rendered.report.object_counts.embedded_svg, 1);
  assert.ok(rendered.zip.file("ppt/charts/chart1.xml"));
  const media = Object.keys(rendered.zip.files).filter(
    (name) => name.startsWith("ppt/media/") && !name.endsWith("/"),
  );
  assert.ok(media.some((name) => name.endsWith(".svg")));
});

test("native backend renders a diagram as editable shapes without embedded media", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "slidethus-native-diagram-"));
  const rendered = await runRenderer(directory, "native", fixture(true));

  assert.equal(rendered.report.measured_editability_level, "E3");
  assert.equal(rendered.report.object_counts.embedded_svg, 0);
  assert.ok(rendered.report.object_counts.shape >= 5);
  const media = Object.keys(rendered.zip.files).filter(
    (name) => name.startsWith("ppt/media/") && !name.endsWith("/"),
  );
  assert.equal(media.length, 0);
});

test("high-cardinality lists render as editable numbered visual units", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "slidethus-list-"));
  const ir = fixture(false);
  ir.slides[0].layout_family = "process";
  ir.slides[0].regions = [
    region(
      1,
      "list",
      [
        "Data foundation",
        "Knowledge layer",
        "Process controls",
        "Policy rules",
        "Tool access",
        "Permissions",
        "Evaluation standard",
      ],
      [120, 120, 1040, 480],
      { style: style({ fill: "#E8EFEE" }) },
    ),
  ];
  const rendered = await runRenderer(directory, "native", ir);

  assert.ok(rendered.report.object_counts.shape >= 8);
  assert.ok(rendered.report.object_counts.text >= 15);
  const slideXml = await rendered.zip.file("ppt/slides/slide1.xml").async("string");
  assert.match(slideXml, /Evaluation standard/);
});
