import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import PptxGenJS from "pptxgenjs";

const LOGICAL_WIDTH = 1280;
const LOGICAL_HEIGHT = 720;
const SLIDE_WIDTH = 13.333333;
const SLIDE_HEIGHT = 7.5;
const EDITABILITY_ORDER = { E0: 0, E1: 1, E2: 2, E3: 3, E4: 4 };

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) {
      throw new Error(`Unexpected argument: ${token}`);
    }
    const key = token.slice(2);
    const value = argv[index + 1];
    if (value === undefined || value.startsWith("--")) {
      throw new Error(`Missing value for --${key}`);
    }
    result[key] = value;
    index += 1;
  }
  return result;
}

function requireArg(args, key) {
  const value = args[key];
  if (!value) {
    throw new Error(`Missing required argument --${key}`);
  }
  return value;
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function color(value, fallback = "000000") {
  const normalized = String(value ?? "").trim().replace(/^#/, "").toUpperCase();
  return /^[0-9A-F]{6}$/.test(normalized) ? normalized : fallback;
}

function x(value) {
  return (Number(value) / LOGICAL_WIDTH) * SLIDE_WIDTH;
}

function y(value) {
  return (Number(value) / LOGICAL_HEIGHT) * SLIDE_HEIGHT;
}

function textValues(content, contentType) {
  if (Array.isArray(content)) {
    return content.map((item) => String(item));
  }
  if (content && typeof content === "object") {
    if (contentType === "table" || contentType === "chart") {
      return [];
    }
    return Object.entries(content).map(([key, value]) => `${key}: ${String(value)}`);
  }
  return [String(content ?? "")];
}

function textOptions(region) {
  const style = region.style;
  return {
    x: x(region.x),
    y: y(region.y),
    w: x(region.w),
    h: y(region.h),
    fontFace: style.font_family,
    fontSize: Number(style.font_size),
    bold: Number(style.font_weight) >= 600,
    color: color(style.color),
    margin: 4,
    breakLine: false,
    valign: region.valign === "middle" ? "mid" : region.valign,
    align: region.align,
    isTextBox: true,
    lineSpacingMultiple: Number(style.line_height),
    transparency: 0,
  };
}

function addSurface(slide, pptx, region) {
  const style = region.style;
  if (!style.fill && !style.border_color) {
    return;
  }
  slide.addShape(pptx.ShapeType.roundRect, {
    x: x(region.x),
    y: y(region.y),
    w: x(region.w),
    h: y(region.h),
    rectRadius: 0.08,
    fill: style.fill
      ? { color: color(style.fill, "FFFFFF") }
      : { color: "FFFFFF", transparency: 100 },
    line: style.border_color
      ? {
          color: color(style.border_color, "D8D2C6"),
          width: Math.max(0.25, Number(style.border_width ?? 1)),
        }
      : { color: "FFFFFF", transparency: 100 },
  });
}

function addQualification(slide, region, counts) {
  if (!region.evidence_qualification) {
    return;
  }
  const style = region.style;
  const qualificationHeight = Math.min(0.36, Math.max(0.22, y(region.h) * 0.18));
  slide.addText(`限定：${region.evidence_qualification}`, {
    x: x(region.x) + 0.12,
    y: y(region.y + region.h) - qualificationHeight - 0.04,
    w: Math.max(0.2, x(region.w) - 0.24),
    h: qualificationHeight,
    fontFace: style.font_family,
    fontSize: Math.max(9, Math.min(12, Number(style.font_size) * 0.55)),
    color: "667085",
    italic: true,
    margin: 0,
    breakLine: false,
  });
  counts.text += 1;
}

function addText(slide, region, counts) {
  addSurface(slide, slide._slidethusPptx, region);
  const values = textValues(region.content, region.content_type);
  const separator = region.content_type === "list" ? "\n• " : "\n";
  const rendered =
    region.content_type === "list" && values.length > 0
      ? `• ${values.join(separator)}`
      : values.join(separator);
  const options = textOptions(region);
  if (region.evidence_qualification) {
    options.h = Math.max(0.2, options.h - 0.34);
  }
  slide.addText(rendered, options);
  counts.text += 1;
  addQualification(slide, region, counts);
}

function normalizeTable(content) {
  if (Array.isArray(content) && content.every((row) => Array.isArray(row))) {
    return content.map((row) => row.map((cell) => String(cell)));
  }
  if (content && typeof content === "object") {
    const headers = Array.isArray(content.headers) ? content.headers.map(String) : [];
    const rows = Array.isArray(content.rows)
      ? content.rows.map((row) => {
          if (!Array.isArray(row)) {
            throw new Error("Table rows must be arrays");
          }
          return row.map((cell) => String(cell));
        })
      : [];
    if (headers.length > 0) {
      return [headers, ...rows];
    }
    return rows;
  }
  throw new Error("Table content must be an array of rows or {headers, rows}");
}

function addTable(slide, region, counts) {
  const rows = normalizeTable(region.content);
  if (rows.length === 0 || rows[0].length === 0) {
    throw new Error(`Table ${region.block_id} has no cells`);
  }
  const columnCount = rows[0].length;
  if (rows.some((row) => row.length !== columnCount)) {
    throw new Error(`Table ${region.block_id} has inconsistent column counts`);
  }
  slide.addTable(rows, {
    x: x(region.x),
    y: y(region.y),
    w: x(region.w),
    h: y(region.h),
    border: { type: "solid", color: color(region.style.border_color, "D8D2C6"), pt: 1 },
    fill: color(region.style.fill, "FFFFFF"),
    color: color(region.style.color),
    fontFace: region.style.font_family,
    fontSize: Math.max(9, Math.min(18, Number(region.style.font_size))),
    bold: Number(region.style.font_weight) >= 600,
    margin: 3,
    valign: "mid",
    autoFit: false,
  });
  counts.table += 1;
  addQualification(slide, region, counts);
}

function normalizeChart(content) {
  if (!content || typeof content !== "object" || Array.isArray(content)) {
    throw new Error("Chart content must be an object");
  }
  const type = String(content.type ?? "bar");
  const categories = Array.isArray(content.categories) ? content.categories.map(String) : [];
  const series = Array.isArray(content.series) ? content.series : [];
  if (categories.length === 0 || series.length === 0) {
    throw new Error("Chart content requires categories and series");
  }
  const normalized = series.map((item, index) => {
    const values = Array.isArray(item.values) ? item.values.map(Number) : [];
    if (values.length !== categories.length || values.some((value) => !Number.isFinite(value))) {
      throw new Error(`Chart series ${index + 1} values must match categories and be numeric`);
    }
    return {
      name: String(item.name ?? `Series ${index + 1}`),
      labels: categories,
      values,
    };
  });
  return { type, series: normalized };
}

function addChart(slide, pptx, region, counts) {
  const chart = normalizeChart(region.content);
  const chartType = pptx.ChartType[chart.type] ?? pptx.ChartType.bar;
  slide.addChart(chartType, chart.series, {
    x: x(region.x),
    y: y(region.y),
    w: x(region.w),
    h: y(region.h),
    showTitle: false,
    showLegend: chart.series.length > 1,
    showValue: true,
    showCategoryName: false,
    showPercent: chart.type === "pie" || chart.type === "doughnut",
    catAxisLabelFontFace: region.style.font_family,
    catAxisLabelFontSize: 10,
    valAxisLabelFontFace: region.style.font_family,
    valAxisLabelFontSize: 10,
    chartColors: ["1E4D5C", "D96C4B", "667085", "84A98C", "E9C46A"],
    showCatName: true,
    border: { color: color(region.style.border_color, "D8D2C6"), pt: 1 },
  });
  counts.chart += 1;
  addQualification(slide, region, counts);
}

function svgData(svg) {
  return `data:image/svg+xml;base64,${Buffer.from(svg, "utf8").toString("base64")}`;
}

function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function complexBlockSvg(region) {
  const width = Math.max(1, Number(region.w));
  const height = Math.max(1, Number(region.h));
  const values = textValues(region.content, region.content_type);
  const items = values.length > 0 ? values : [region.semantic_role];
  const fill = region.style.fill ?? "#FFFFFF";
  const stroke = region.style.border_color ?? "#D8D2C6";
  const primary = region.style.color ?? "#17233C";
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.max(18, Math.min(width, height) * 0.12);
  const output = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
    `<rect x="1" y="1" width="${Math.max(1, width - 2)}" height="${Math.max(1, height - 2)}" rx="12" fill="${escapeXml(fill)}" stroke="${escapeXml(stroke)}"/>`,
  ];
  if (region.content_type === "diagram" || region.content_type === "icon") {
    const gap = width / (items.length + 1);
    items.forEach((item, index) => {
      const cx = gap * (index + 1);
      output.push(
        `<circle cx="${cx}" cy="${centerY}" r="${radius}" fill="#1E4D5C"/>`,
        `<text x="${cx}" y="${centerY + 5}" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" fill="#FFFFFF">${escapeXml(String(item).slice(0, 18))}</text>`,
      );
      if (index < items.length - 1) {
        output.push(
          `<line x1="${cx + radius}" y1="${centerY}" x2="${gap * (index + 2) - radius}" y2="${centerY}" stroke="#D96C4B" stroke-width="3"/>`,
        );
      }
    });
  } else {
    output.push(
      `<text x="${centerX}" y="${centerY}" text-anchor="middle" font-family="Arial,sans-serif" font-size="22" font-weight="700" fill="${escapeXml(primary)}">${escapeXml(items.join(" · ").slice(0, 90))}</text>`,
    );
  }
  output.push("</svg>");
  return output.join("");
}

function resolveAsset(assetMap, assetId) {
  const asset = assetMap[assetId];
  if (!asset) {
    throw new Error(`Unknown renderer asset: ${assetId}`);
  }
  if (!asset.path || !fs.existsSync(asset.path)) {
    throw new Error(`Renderer asset is missing: ${assetId}`);
  }
  return asset;
}

function addAssetImage(slide, region, assetMap, counts) {
  if (!Array.isArray(region.asset_refs) || region.asset_refs.length !== 1) {
    throw new Error(`Asset block ${region.block_id} must bind exactly one asset`);
  }
  const asset = resolveAsset(assetMap, region.asset_refs[0]);
  slide.addImage({
    path: asset.path,
    x: x(region.x),
    y: y(region.y),
    w: x(region.w),
    h: y(region.h),
    transparency: 0,
  });
  counts.image += 1;
  addQualification(slide, region, counts);
}

function addHybridComplex(slide, region, assetMap, counts) {
  if (Array.isArray(region.asset_refs) && region.asset_refs.length > 0) {
    addAssetImage(slide, region, assetMap, counts);
    return;
  }
  const svg = complexBlockSvg(region);
  slide.addImage({
    data: svgData(svg),
    x: x(region.x),
    y: y(region.y),
    w: x(region.w),
    h: y(region.h),
  });
  counts.embedded_svg += 1;
  addQualification(slide, region, counts);
}

function addNativeComplex(slide, pptx, region, assetMap, counts) {
  if (Array.isArray(region.asset_refs) && region.asset_refs.length > 0) {
    addAssetImage(slide, region, assetMap, counts);
    return;
  }
  const values = textValues(region.content, region.content_type);
  const items = values.length > 0 ? values : [region.semantic_role];
  const left = x(region.x);
  const top = y(region.y);
  const width = x(region.w);
  const height = y(region.h);
  if (region.content_type === "icon") {
    const size = Math.min(width, height) * 0.58;
    const nodeX = left + (width - size) / 2;
    const nodeY = top + (height - size) / 2;
    slide.addShape(pptx.ShapeType.ellipse, {
      x: nodeX,
      y: nodeY,
      w: size,
      h: size,
      fill: { color: "154C5A" },
      line: { color: "154C5A", width: 1 },
    });
    slide.addText(String(items[0]).slice(0, 24), {
      x: nodeX + 0.05,
      y: nodeY + size * 0.35,
      w: Math.max(0.2, size - 0.1),
      h: Math.max(0.2, size * 0.3),
      fontFace: region.style.font_family,
      fontSize: Math.max(10, Math.min(18, Number(region.style.font_size))),
      bold: true,
      color: "FFFFFF",
      align: "center",
      valign: "mid",
      margin: 0,
    });
    counts.shape += 1;
    counts.text += 1;
    addQualification(slide, region, counts);
    return;
  }
  const gap = width / (items.length + 1);
  const nodeW = Math.max(0.75, Math.min(1.55, gap * 0.58));
  const nodeH = Math.max(0.45, Math.min(0.8, height * 0.38));
  const centerY = top + height / 2;
  items.forEach((item, index) => {
    const centerX = left + gap * (index + 1);
    const nodeX = centerX - nodeW / 2;
    const nodeY = centerY - nodeH / 2;
    if (index < items.length - 1) {
      const nextCenter = left + gap * (index + 2);
      slide.addShape(pptx.ShapeType.line, {
        x: centerX + nodeW / 2,
        y: centerY,
        w: Math.max(0.05, nextCenter - centerX - nodeW),
        h: 0,
        line: { color: "D76745", width: 2.25, beginArrowType: "none", endArrowType: "triangle" },
      });
      counts.shape += 1;
    }
    slide.addShape(pptx.ShapeType.roundRect, {
      x: nodeX,
      y: nodeY,
      w: nodeW,
      h: nodeH,
      fill: { color: "154C5A" },
      line: { color: "154C5A", width: 1 },
    });
    slide.addText(String(item).slice(0, 28), {
      x: nodeX + 0.04,
      y: nodeY + 0.04,
      w: Math.max(0.2, nodeW - 0.08),
      h: Math.max(0.2, nodeH - 0.08),
      fontFace: region.style.font_family,
      fontSize: Math.max(9, Math.min(14, Number(region.style.font_size) * 0.7)),
      bold: true,
      color: "FFFFFF",
      align: "center",
      valign: "mid",
      margin: 0,
    });
    counts.shape += 1;
    counts.text += 1;
  });
  addQualification(slide, region, counts);
}

function addDecoration(slide, pptx, item, counts) {
  const shapeMap = {
    rect: pptx.ShapeType.rect,
    round_rect: pptx.ShapeType.roundRect,
    ellipse: pptx.ShapeType.ellipse,
    line: pptx.ShapeType.line,
  };
  const shapeType = shapeMap[item.kind];
  if (!shapeType) {
    throw new Error(`Unsupported decoration kind: ${item.kind}`);
  }
  const options = {
    x: x(item.x),
    y: y(item.y),
    w: x(item.w),
    h: y(item.h),
    fill: item.fill
      ? { color: color(item.fill, "FFFFFF") }
      : { color: "FFFFFF", transparency: 100 },
    line: item.stroke
      ? { color: color(item.stroke, "000000"), width: 1 }
      : { color: "FFFFFF", transparency: 100 },
  };
  if (item.kind === "line") {
    delete options.fill;
  }
  slide.addShape(shapeType, options);
  counts.shape += 1;
}

function addRegion(slide, pptx, region, mode, assetMap, counts) {
  const type = String(region.content_type);
  if (["text", "list", "metric", "quote", "spacer"].includes(type)) {
    addText(slide, region, counts);
    return;
  }
  if (type === "table") {
    addSurface(slide, pptx, region);
    addTable(slide, region, counts);
    return;
  }
  if (type === "chart") {
    addSurface(slide, pptx, region);
    addChart(slide, pptx, region, counts);
    return;
  }
  if (type === "image") {
    addAssetImage(slide, region, assetMap, counts);
    return;
  }
  if (["icon", "diagram"].includes(type)) {
    if (mode === "native") {
      addNativeComplex(slide, pptx, region, assetMap, counts);
    } else {
      addHybridComplex(slide, region, assetMap, counts);
    }
    return;
  }
  throw new Error(`Unsupported content type ${type} for ${region.block_id}`);
}

function validateIr(ir) {
  if (!ir || typeof ir !== "object") {
    throw new Error("Renderer IR must be an object");
  }
  if (!Array.isArray(ir.slides) || ir.slides.length === 0) {
    throw new Error("Renderer IR contains no slides");
  }
  if (Number(ir.canvas?.width) !== LOGICAL_WIDTH || Number(ir.canvas?.height) !== LOGICAL_HEIGHT) {
    throw new Error("PptxGenJS renderer requires 1280x720 logical canvas");
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const mode = requireArg(args, "mode");
  if (!new Set(["native", "hybrid"]).has(mode)) {
    throw new Error(`Unsupported renderer mode: ${mode}`);
  }
  const inputPath = path.resolve(requireArg(args, "input"));
  const outputPath = path.resolve(requireArg(args, "output"));
  const reportPath = path.resolve(requireArg(args, "report"));
  const targetEditability = args["target-editability"] ?? (mode === "native" ? "E3" : "E2");
  if (!(targetEditability in EDITABILITY_ORDER)) {
    throw new Error(`Unsupported target editability: ${targetEditability}`);
  }
  const assetMap = args.assets ? readJson(path.resolve(args.assets)) : {};
  const ir = readJson(inputPath);
  validateIr(ir);

  const pptx = new PptxGenJS();
  pptx.defineLayout({ name: "SLIDETHUS_WIDE", width: SLIDE_WIDTH, height: SLIDE_HEIGHT });
  pptx.layout = "SLIDETHUS_WIDE";
  pptx.author = "Slidethus";
  pptx.company = "Slidethus";
  pptx.subject = `Renderer IR ${ir.ir_id}`;
  pptx.title = ir.deck_id;
  pptx.lang = "zh-CN";
  pptx.revision = "1";

  const counts = {
    text: 0,
    shape: 0,
    table: 0,
    chart: 0,
    image: 0,
    embedded_svg: 0,
  };
  for (const slideIr of ir.slides) {
    const slide = pptx.addSlide();
    slide._slidethusPptx = pptx;
    slide.background = { color: color(ir.canvas.background, "FFFFFF") };
    const objects = [
      ...slideIr.decorations.map((item) => ({ z: Number(item.z), kind: "decoration", item })),
      ...slideIr.regions.map((item) => ({ z: Number(item.z), kind: "region", item })),
    ].sort((left, right) => left.z - right.z || left.kind.localeCompare(right.kind));
    for (const object of objects) {
      if (object.kind === "decoration") {
        addDecoration(slide, pptx, object.item, counts);
      } else {
        addRegion(slide, pptx, object.item, mode, assetMap, counts);
      }
    }
    slide.addText(`${slideIr.slide_id} · ${slideIr.ordinal}`, {
      x: 11.9,
      y: 7.16,
      w: 1.0,
      h: 0.16,
      fontFace: ir.fonts[0] ?? "Arial",
      fontSize: 8,
      color: "667085",
      align: "right",
      margin: 0,
    });
    counts.text += 1;
  }

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  await pptx.writeFile({ fileName: outputPath });
  const measured =
    mode === "hybrid" || counts.image > 0 || counts.embedded_svg > 0 ? "E2" : "E3";
  const warnings = [];
  if (EDITABILITY_ORDER[measured] < EDITABILITY_ORDER[targetEditability]) {
    warnings.push(
      `${mode} backend measured editability ${measured}, below requested ${targetEditability}.`,
    );
  }
  const report = {
    backend: mode === "native" ? "pptxgenjs-native" : "pptxgenjs-hybrid",
    backend_version: "1.0.0",
    pptxgenjs_version: "4.0.1",
    mode,
    ir_id: ir.ir_id,
    output_path: outputPath,
    slide_count: ir.slides.length,
    object_counts: counts,
    target_editability_level: targetEditability,
    measured_editability_level: measured,
    warnings,
  };
  writeJson(reportPath, report);
}

main().catch((error) => {
  console.error(error?.stack ?? String(error));
  process.exitCode = 1;
});
