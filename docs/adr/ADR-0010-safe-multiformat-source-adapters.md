# ADR-0010｜Safe Multi-format Source Adapters

- Status: Accepted
- Date: 2026-08-27

## Context

M2.1 established one provider-neutral Parser Registry and immutable source snapshots, but admitted only Markdown/TXT. Presentation engineering also depends on HTML, PDF, DOCX, PPTX, CSV/XLSX and images. Treating every decodable file as plain text would destroy native locators, miss container risks and falsely claim capability. Letting each format build a private cache or source model would fragment lineage and recovery.

OOXML and image/PDF formats also introduce resource and safety concerns that do not exist in plain text: compressed expansion, duplicate ZIP members, path traversal, encrypted members, macros, ActiveX/OLE embeddings, external relationships, formulas, high-pixel images and content that cannot be interpreted without OCR or media understanding.

## Decision

M2.2 extends the M2.1 ingestion contract through independent adapters behind the existing `SourceParser` protocol and Parser Registry.

### Adapter set

- HTML and CSV/TSV use the Python standard library.
- PDF uses optional `pypdf`.
- DOCX uses optional `python-docx`.
- PPTX uses the existing `python-pptx` dependency.
- XLSX uses optional `openpyxl`.
- PNG/JPEG/GIF/WebP/BMP/TIFF/ICO metadata uses optional Pillow.
- Optional parsers are installed through `slidethus[ingestion]`; missing dependencies raise `SourceCapabilityError` with an actionable install instruction.

Detection and admission remain separate. A signature may identify a format, but only an admitted adapter may return a successful parse. SVG, legacy OLE Office files, macro-enabled OOXML and other unimplemented families remain unsupported.

### Format-native facts

Adapters emit the same `SourceParseResult`, stable Chunk IDs and immutable Source Snapshot used by M2.1, with native locators:

- HTML semantic element/table-row locators;
- PDF page locators;
- DOCX paragraph, table, header/footer, textbox and image-alt locators;
- PPTX slide/shape/table/chart/notes/image-metadata locators;
- CSV logical-row plus physical-line locators;
- XLSX sheet/row/cell coordinates;
- image and EXIF metadata locators.

Links, formulas and source instructions are preserved as data and never opened or evaluated.

### Resource and container controls

`SourceParseLimits` adds explicit limits for risks, pages, slides, sheets, rows, cells, ZIP entries, one ZIP member, total uncompressed bytes and image pixels. Limits are part of snapshot lineage and therefore invalidate cache reuse when changed.

Before any OOXML library opens a package, ZIP preflight rejects:

- excessive entries, member size or total expansion;
- duplicate or case-colliding member names;
- absolute, traversing, drive-qualified or symlink members;
- encrypted entries;
- VBA parts or macro-enabled content types;
- DTD/entity declarations in relationship files.

External relationships and embedded objects are recorded but never opened. Standard embedded Office workbooks used by charts are warnings rather than high-severity executable-content findings; ActiveX and unknown binary embeddings remain high severity.

### Capability truthfulness

Successful parsing distinguishes:

- `parsed`: the admitted semantic contract was fully extracted;
- `partial`: useful facts were extracted, but recorded content classes remain uninterpreted or omitted.

Examples of `partial` include image metadata without OCR, Office images/media, comments/endnotes/equations, SmartArt, unsupported chart presentation semantics, embedded objects, PDF pages without extractable text, annotations or forms. A file with no usable admitted facts fails instead of producing an empty successful snapshot.

The Source Ledger and Source Snapshot must agree on parse status. Both `parsed` and `partial` production records require a valid immutable snapshot.

### Non-goals

M2.2 does not execute macros, scripts, formulas, hyperlinks or embedded files. It does not perform OCR, image understanding, audio/video interpretation, PDF rendering, formula calculation, Web fetching, Evidence normalization or existing-deck visual reconstruction.

## Consequences

- Multi-format inputs share one identity, lineage, cache, validation and recovery model.
- Format-native locators can support later Evidence binding without reparsing through ad hoc code.
- Optional dependencies increase the tested environment and third-party notice surface but do not burden the deterministic core install.
- Some visually rich sources intentionally remain `partial`; later OCR/vision/media capabilities must create new versioned adapters rather than silently expanding current claims.
- M2.2 completes source-format adapters only. Research runtime and the Evidence Engine remain M2.3–M2.5 work, so the M2-wide Exit Gate is still open.
