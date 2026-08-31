// Backend adapter only: all content, geometry and appearance come from admitted IR.
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const [inputPath, outputDir, moduleRoot] = process.argv.slice(2);
if (!inputPath || !outputDir || !moduleRoot) throw new Error("Expected input, output and host module directory");
const requireHost = createRequire(path.join(moduleRoot, "slidethus-host.cjs"));
const { Presentation, PresentationFile } = await import(pathToFileURL(requireHost.resolve("@oai/artifact-tool")).href);
const input = JSON.parse(await fs.readFile(inputPath, "utf8"));
const { ir, assets, slide_ids: selected, notes } = input;
const deck = Presentation.create({ slideSize: { width: ir.canvas.width, height: ir.canvas.height } });
const frame = r => ({ left: r.x, top: r.y, width: r.w, height: r.h });
const line = (fill, width) => ({ style: "solid", fill: fill ?? "none", width });
const textStyle = r => ({
  typeface: r.style.font_family, fontSize: r.style.font_size * 4 / 3,
  bold: r.style.font_weight >= 600, italic: r.style.italic ?? false,
  color: r.style.color, alignment: r.align, verticalAlignment: r.valign,
  lineSpacing: r.style.line_height, autoFit: "none", wrap: "square",
  insets: { top: 0, right: 0, bottom: 0, left: 0 },
});

function visibleText(content) {
  if (typeof content === "string" || typeof content === "number") return String(content);
  if (Array.isArray(content) && content.every(v => typeof v === "string" || typeof v === "number")) return content.join("\n");
  throw new Error("Text must be a string, number or primitive list; return to Slide Specs instead of flattening structured content");
}

async function renderRegion(slide, r, page) {
  if (["clip", "paginate"].includes(r.overflow_strategy)) throw new Error(`Unsupported overflow strategy: ${r.overflow_strategy}`);
  const style = r.style;
  const type = r.content_type;
  if (type === "spacer") return;
  if (["text", "list", "metric", "quote"].includes(type)) {
    const shape = slide.shapes.add({
      name: r.block_id, geometry: "textbox", position: frame(r),
      fill: style.fill ?? "none", line: line(style.border_color, style.border_width),
      borderRadius: style.corner_radius ?? 0,
    });
    shape.text = visibleText(r.content) + (r.evidence_qualification ? `\n${r.evidence_qualification}` : "");
    shape.text.style = textStyle(r);
    return;
  }
  // Qualified non-text evidence needs its own visible caption in the page plan.
  if (r.evidence_qualification && !page.regions.some(other =>
    ["text", "list", "quote"].includes(other.content_type) &&
    visibleText(other.content).includes(r.evidence_qualification)
  )) throw new Error(`Non-text qualification needs a planned visible caption: ${r.block_id}`);
  if (["image", "icon", "diagram"].includes(type)) {
    if (r.asset_refs.length !== 1) throw new Error(`Image/diagram requires exactly one admitted asset: ${r.block_id}`);
    const asset = assets[r.asset_refs[0]];
    if (!asset || !["image/png", "image/jpeg"].includes(asset.media_type)) throw new Error("This adapter requires verified PNG/JPEG assets; convert explicitly before admission");
    if (!style.image_fit) throw new Error("Image fit must be explicit");
    const blob = await fs.readFile(asset.path);
    slide.images.add({ blob, contentType: asset.media_type, alt: visibleText(r.content),
      position: frame(r), fit: style.image_fit, geometry: "rect", borderRadius: style.corner_radius ?? 0 });
    return;
  }
  if (type === "chart") {
    const c = r.content;
    if (!c || !["bar", "line", "pie", "doughnut", "area"].includes(c.type)) throw new Error("Unsupported chart type; no fallback chart is invented");
    if (Object.keys(c).some(k => !["type", "categories", "series"].includes(k))) throw new Error("Unsupported chart content field");
    if (!Array.isArray(c.categories) || !c.categories.length || !c.categories.every(v => typeof v === "string")) throw new Error("Chart categories must be nonempty strings");
    if (!Array.isArray(c.series) || !c.series.length || !style.chart_colors?.length) throw new Error("Chart requires data and explicit colors");
    const series = c.series.map((s, i) => {
      if (Object.keys(s).some(k => !["name", "values"].includes(k)) || typeof s.name !== "string" || !Array.isArray(s.values) || s.values.length !== c.categories.length || !s.values.every(v => typeof v === "number" && Number.isFinite(v))) throw new Error("Chart data must be finite numbers aligned with categories");
      const fill = style.chart_colors[i % style.chart_colors.length];
      return { name: s.name, values: s.values, fill, line: line(fill, 2) };
    });
    slide.charts.add(c.type, { position: frame(r), categories: c.categories, series,
      hasLegend: series.length > 1, chartFill: style.fill ?? "none", plotAreaFill: style.fill ?? "none",
      chartLine: line(style.border_color, style.border_width),
      xAxis: { textStyle: { fontSize: style.font_size * 4 / 3, fill: style.color } },
      yAxis: { textStyle: { fontSize: style.font_size * 4 / 3, fill: style.color } },
      legend: { textStyle: { fontSize: style.font_size * 4 / 3, fill: style.color } },
      dataLabels: { showValue: true, textStyle: { fontSize: style.font_size * 4 / 3, fill: style.color } },
    });
    return;
  }
  if (type === "table") {
    const c = r.content;
    if (!Array.isArray(c) && (!c || Object.keys(c).some(k => !["headers", "rows"].includes(k)))) throw new Error("Unsupported table content field");
    const rows = Array.isArray(c) ? c : [...(c.headers?.length ? [c.headers] : []), ...(c.rows ?? [])];
    if (!rows.length || !rows[0].length || rows.some(row => !Array.isArray(row) || row.length !== rows[0].length || row.some(v => !["string", "number"].includes(typeof v)))) throw new Error("Table requires a rectangular primitive matrix");
    const table = slide.tables.add({ rows: rows.length, columns: rows[0].length,
      left: r.x, top: r.y, width: r.w, height: r.h, values: rows });
    table.borders.assign(line(style.border_color, style.border_width));
    for (let y = 0; y < rows.length; y++) for (let x = 0; x < rows[0].length; x++) {
      const cell = table.getCell(y, x);
      cell.fill = style.fill ?? "none";
      cell.text.style = textStyle(r);
    }
    return;
  }
  throw new Error(`Unsupported content_type=${type}; no raster/text fallback`);
}

// The same loop builds samples and full decks. No sample-only layout or authoring path.
for (const page of ir.slides.filter(s => selected.includes(s.slide_id))) {
  const slide = deck.slides.add();
  slide.background.fill = page.background ?? ir.canvas.background;
  const items = [...page.decorations.map(d => ({ ...d, decoration: true })), ...page.regions];
  items.sort((a, b) => a.z - b.z); // stable: decorations precede regions at equal z
  for (const item of items) {
    if (item.decoration) slide.shapes.add({
      name: item.decoration_id, geometry: item.kind === "round_rect" ? "roundRect" : item.kind,
      position: frame(item), fill: item.fill ?? "none", line: line(item.stroke, item.stroke ? 1 : 0),
    });
    else await renderRegion(slide, item, page);
  }
  slide.speakerNotes.textFrame.setText(notes[page.slide_id] ?? "");
}
if (deck.slides.items.length !== selected.length) throw new Error("Slide selection coverage mismatch");
await fs.mkdir(outputDir, { recursive: true });
const pptx = await PresentationFile.exportPptx(deck);
await pptx.save(path.join(outputDir, "candidate.pptx"));
for (const [index, slide] of deck.slides.items.entries()) {
  const id = selected[index];
  const png = await deck.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(path.join(outputDir, `${id}.png`), new Uint8Array(await png.arrayBuffer()));
  await fs.writeFile(path.join(outputDir, `${id}.layout.json`), await (await slide.export({ format: "layout" })).text());
}
