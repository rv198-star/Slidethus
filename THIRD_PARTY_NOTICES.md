# Third-Party Source Boundary

This package was derived from a user-provided saved HTML page titled “应该是目前最强的PPT Agent，附上完整思路分享” and retains only cleaned extraction notes and source-preserved prompts.

The retained files are design research inputs:

- original browser HTML: intentionally omitted from this bootstrap package
- `source_material/cleaned-main-post.md`
- `source_material/source-preserved/`

Rules:

- Preserve source excerpts and prompts verbatim in `source-preserved`.
- Put repairs, extensions, and production prompt contracts in separate files.
- Do not imply ownership, endorsement, or license transfer.
- Do not ship raw third-party material in a public release without a rights review.
- Slidethus architecture decisions are documented separately and are not claims made by the source author.

## Runtime dependencies

The Python package resolves, but does not vendor, runtime dependencies or their transitive dependencies. Current direct dependencies and optional ingestion adapters include:

- `jsonschema` — MIT — Draft 2020-12 artifact and snapshot validation;
- `python-pptx` — MIT — editable PPTX generation and PPTX source parsing;
- `pypdf` — BSD-3-Clause — optional PDF text extraction;
- `python-docx` — MIT — optional DOCX text/table/story extraction;
- `openpyxl` — MIT — optional XLSX cell extraction without formula evaluation;
- `Pillow` — MIT-CMU — optional raster-image verification and bounded metadata/EXIF extraction without OCR.

LibreOffice, Poppler, and Fontconfig tools are optional host capabilities used for preview. Review the license notices supplied by each installed distribution before redistributing an environment or binary bundle.

Fonts discovered on the host are copied only into a temporary LibreOffice profile for the duration of preview. Slidethus does not embed or redistribute those font files in the PPTX, workspace, package, or delivery.
