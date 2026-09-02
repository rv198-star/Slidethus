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
const TABLE_CELL_MARGINS = { top: 4, right: 8, bottom: 4, left: 8 };

function tableGlyphUnits(value) {
  let units = 0;
  for (const char of String(value)) units += char.codePointAt(0) <= 0x7f ? 0.56 : 1;
  return units;
}

function tableLayout(rows, r) {
  const columns = rows[0].length;
  const horizontalPadding = TABLE_CELL_MARGINS.left + TABLE_CELL_MARGINS.right;
  const verticalPadding = TABLE_CELL_MARGINS.top + TABLE_CELL_MARGINS.bottom;
  const availableTextWidth = r.w - horizontalPadding * columns;
  const demands = Array.from({ length: columns }, (_, x) =>
    Math.max(1, ...rows.map(row => tableGlyphUnits(row[x]))));
  const totalDemand = demands.reduce((sum, value) => sum + value, 0);
  const columnWidths = demands.map(demand => availableTextWidth <= 0
    ? r.w / columns
    : horizontalPadding + availableTextWidth * demand / totalDemand);
  const fontPx = Math.max(1, r.style.font_size * 4 / 3);
  const requiredRows = rows.map(row => {
    const lines = Math.max(...row.map((value, x) => Math.max(1,
      Math.ceil(tableGlyphUnits(value) /
        Math.max(1, (columnWidths[x] - horizontalPadding) / fontPx)))));
    return lines * fontPx * r.style.line_height + verticalPadding;
  });
  const requiredHeight = requiredRows.reduce((sum, value) => sum + value, 0);
  const extra = requiredHeight <= r.h ? (r.h - requiredHeight) / rows.length : 0;
  return {
    fits: requiredHeight <= r.h,
    requiredHeight,
    columnWidths,
    rowHeights: requiredRows.map(value => value + extra),
  };
}

function visibleText(content) {
  if (typeof content === "string" || typeof content === "number") return String(content);
  if (Array.isArray(content) && content.every(v => typeof v === "string" || typeof v === "number")) return content.join("\n");
  throw new Error("Text must be a string, number or primitive list; return to Slide Specs instead of flattening structured content");
}

function editableDiagram(content) {
  if (!content || Array.isArray(content) || Object.keys(content).some(k => !["nodes", "edges"].includes(k))) {
    throw new Error("Editable diagram requires only nodes and edges");
  }
  const nodes = content.nodes;
  const edges = content.edges ?? [];
  if (!Array.isArray(nodes) || !nodes.length || !Array.isArray(edges)) {
    throw new Error("Editable diagram requires nonempty nodes and an edge list");
  }
  const ids = new Set();
  for (const node of nodes) {
    if (!node || Object.keys(node).some(k => !["id", "label", "x", "y", "w", "h"].includes(k)) ||
      typeof node.id !== "string" || !node.id.trim() || typeof node.label !== "string" || !node.label.trim() ||
      ![node.x, node.y, node.w, node.h].every(v => typeof v === "number" && Number.isFinite(v)) ||
      node.x < 0 || node.y < 0 || node.w <= 0 || node.h <= 0 || node.x + node.w > 1 || node.y + node.h > 1 ||
      ids.has(node.id)) throw new Error("Editable diagram nodes require unique IDs, labels and normalized geometry");
    ids.add(node.id);
  }
  for (const edge of edges) {
    if (!edge || Object.keys(edge).some(k => !["from", "to", "label"].includes(k)) ||
      typeof edge.from !== "string" || typeof edge.to !== "string" || !ids.has(edge.from) || !ids.has(edge.to) ||
      edge.from === edge.to || (edge.label !== undefined && typeof edge.label !== "string")) {
      throw new Error("Editable diagram edges must reference distinct admitted nodes");
    }
  }
  return { nodes, edges };
}

function renderEditableDiagram(slide, r) {
  const { nodes, edges } = editableDiagram(r.content);
  const byId = new Map(nodes.map(node => [node.id, node]));
  const position = node => ({
    left: r.x + node.x * r.w, top: r.y + node.y * r.h,
    width: node.w * r.w, height: node.h * r.h,
  });
  for (const edge of edges) {
    const source = position(byId.get(edge.from));
    const target = position(byId.get(edge.to));
    const x1 = source.left + source.width / 2;
    const y1 = source.top + source.height / 2;
    const x2 = target.left + target.width / 2;
    const y2 = target.top + target.height / 2;
    if (x1 !== x2) slide.shapes.add({
      name: `${r.block_id}-edge-${edge.from}-${edge.to}-h`, geometry: "line",
      position: { left: Math.min(x1, x2), top: y1, width: Math.abs(x2 - x1), height: 0 },
      fill: "none", line: line(r.style.border_color ?? r.style.color, Math.max(1, r.style.border_width)),
    });
    if (y1 !== y2) slide.shapes.add({
      name: `${r.block_id}-edge-${edge.from}-${edge.to}-v`, geometry: "line",
      position: { left: x2, top: Math.min(y1, y2), width: 0, height: Math.abs(y2 - y1) },
      fill: "none", line: line(r.style.border_color ?? r.style.color, Math.max(1, r.style.border_width)),
    });
    if (edge.label) {
      const labelWidth = Math.min(120, r.w);
      const labelHeight = Math.min(24, r.h);
      const labelLeft = Math.max(r.x, Math.min(
        (x1 + x2) / 2 - labelWidth / 2,
        r.x + r.w - labelWidth,
      ));
      const labelTop = Math.max(r.y, Math.min(
        (y1 + y2) / 2 - labelHeight / 2,
        r.y + r.h - labelHeight,
      ));
      const label = slide.shapes.add({
        name: `${r.block_id}-edge-${edge.from}-${edge.to}-label`, geometry: "textbox",
        position: { left: labelLeft, top: labelTop, width: labelWidth, height: labelHeight },
        fill: r.style.fill ?? "none", line: line("none", 0),
      });
      label.text = edge.label;
      label.text.style = textStyle(r);
    }
  }
  for (const node of nodes) {
    const shape = slide.shapes.add({
      name: `${r.block_id}-node-${node.id}`, geometry: "roundRect",
      position: position(node), fill: r.style.fill ?? "none",
      line: line(r.style.border_color ?? r.style.color, Math.max(1, r.style.border_width)),
      borderRadius: r.style.corner_radius ?? 8,
    });
    shape.text = node.label;
    shape.text.style = textStyle(r);
  }
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
  if (type === "diagram" && r.asset_refs.length === 0) {
    renderEditableDiagram(slide, r);
    return;
  }
  if (["image", "icon", "diagram"].includes(type)) {
    if (r.asset_refs.length !== 1) throw new Error(`Raster image/diagram requires exactly one admitted asset: ${r.block_id}`);
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
    const layout = tableLayout(rows, r);
    if (!layout.fits) throw new Error(`Table text needs ${layout.requiredHeight.toFixed(1)}px but ${r.h.toFixed(1)}px is available: ${r.block_id}`);
    const table = slide.tables.add({ rows: rows.length, columns: rows[0].length,
      left: r.x, top: r.y, width: r.w, height: r.h, values: rows });
    table.cellMargins = TABLE_CELL_MARGINS;
    table.setColumnWidths(layout.columnWidths);
    for (let y = 0; y < rows.length; y++) table.rows[y].height = layout.rowHeights[y];
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
