import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { Resvg } from "@resvg/resvg-js";
import { PDFDocument } from "pdf-lib";

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) {
      throw new Error(`Unexpected argument: ${token}`);
    }
    const value = argv[index + 1];
    if (value === undefined || value.startsWith("--")) {
      throw new Error(`Missing value for ${token}`);
    }
    result[token.slice(2)] = value;
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

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const inputs = readJson(path.resolve(requireArg(args, "inputs")));
  const pngDir = path.resolve(requireArg(args, "png-dir"));
  const pdfPath = path.resolve(requireArg(args, "pdf"));
  const reportPath = path.resolve(requireArg(args, "report"));
  const generatedAt = new Date(args["generated-at"] ?? "1980-01-01T00:00:00Z");
  if (!Array.isArray(inputs) || inputs.length === 0) {
    throw new Error("Preview input list is empty");
  }
  if (Number.isNaN(generatedAt.valueOf())) {
    throw new Error("Invalid --generated-at timestamp");
  }

  fs.mkdirSync(pngDir, { recursive: true });
  fs.mkdirSync(path.dirname(pdfPath), { recursive: true });
  const pdf = await PDFDocument.create();
  pdf.setTitle("Slidethus Render Preview");
  pdf.setAuthor("Slidethus");
  pdf.setProducer("Slidethus @resvg/resvg-js + pdf-lib");
  pdf.setCreator("Slidethus");
  pdf.setCreationDate(generatedAt);
  pdf.setModificationDate(generatedAt);

  const outputs = [];
  for (let index = 0; index < inputs.length; index += 1) {
    const input = inputs[index];
    const slideId = String(input.slide_id ?? `S-${String(index + 1).padStart(3, "0")}`);
    const svgPath = path.resolve(String(input.path));
    const svg = fs.readFileSync(svgPath, "utf8");
    const renderer = new Resvg(svg, {
      fitTo: { mode: "width", value: 1920 },
      font: {
        loadSystemFonts: true,
        defaultFontFamily: "Arial",
      },
    });
    const png = renderer.render().asPng();
    const pngPath = path.join(pngDir, `${slideId}.png`);
    fs.writeFileSync(pngPath, png);
    const embedded = await pdf.embedPng(png);
    const page = pdf.addPage([960, 540]);
    page.drawImage(embedded, { x: 0, y: 0, width: 960, height: 540 });
    outputs.push({
      slide_id: slideId,
      svg_path: svgPath,
      png_path: pngPath,
      png_width: embedded.width,
      png_height: embedded.height,
    });
  }

  const pdfBytes = await pdf.save({ useObjectStreams: false, addDefaultPage: false });
  fs.writeFileSync(pdfPath, pdfBytes);
  fs.writeFileSync(
    reportPath,
    `${JSON.stringify(
      {
        renderer: "resvg-pdf-lib-preview",
        renderer_version: "1.0.0",
        resvg_version: "2.6.2",
        pdf_lib_version: "1.17.1",
        slide_count: outputs.length,
        outputs,
        pdf_path: pdfPath,
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
}

main().catch((error) => {
  console.error(error?.stack ?? String(error));
  process.exitCode = 1;
});
