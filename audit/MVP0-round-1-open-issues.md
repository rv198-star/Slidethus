# MVP0 Round 1 — Open Issue Mining

Date: 2026-08-26

Scope: Markdown/TXT ingestion, rule-based planning, native PPTX, independent preview, Gate persistence and degraded delivery. Scores were intentionally withheld until issues were fixed.

## Issues found

### ISS-MVP0-001 — Major — staged artifact validation blocked legal Outline publication

- Location: `src/slidethus/validation.py`
- Finding: absent downstream Slide Specs/Layout were treated as empty published artifacts, so Outline could not be written before P5A/P5B.
- Impact: the documented state machine could not execute stage by stage.
- Root phase: M1 Artifact Runtime validation.
- Fix: run coverage equality only when the downstream artifact has actually been published.
- Verification: `test_staged_outline_does_not_require_unpublished_downstream_artifacts`.
- Status: fixed.

### ISS-MVP0-002 — Major — passing G0 left the bootstrap blocker open

- Location: `src/slidethus/artifact_runtime.py`
- Finding: G0 advanced to `BRIEF_READY` while `BKR-001` remained open, producing an active-state/blocker contradiction on the next validation.
- Impact: a valid Brief could not continue reliably.
- Root phase: M1 Gate persistence.
- Fix: a passing/waived G0 resolves the known bootstrap Brief blocker in the same transaction.
- Verification: the staged-publication regression test and all end-to-end MVP tests.
- Status: fixed.

### ISS-MVP0-003 — Major — LibreOffice could not initialize a reusable user profile

- Location: `src/slidethus/pptx_backend.py`
- Finding: headless conversion failed with “User installation could not be completed.”
- Impact: independent preview was unavailable and G8/G9 correctly remained blocked.
- Root phase: P7 preview adapter.
- Fix: create a unique temporary `UserInstallation` profile per run.
- Verification: six-page LibreOffice/Poppler acceptance render.
- Status: fixed.

### ISS-MVP0-004 — Critical — Chinese glyphs disappeared in independent preview

- Location: `src/slidethus/minimal_providers.py`, `src/slidethus/pptx_backend.py`
- Finding: the initial Arial/PingFang attempt rendered Chinese as blank text or tofu boxes in LibreOffice.
- Impact: a Chinese deck appeared to render successfully while losing core content.
- Root phase: P6 font policy and P7 preview environment.
- Fix: write explicit East Asian OOXML typefaces, choose a platform CJK family, discover the actual host font, copy it only to the isolated LibreOffice profile, and reject CJK preview when no font can be staged.
- Verification: independent PNGs show all Chinese text on cover, agenda, body and final slide; test checks East Asian typeface markup.
- Status: fixed.

### ISS-MVP0-005 — Major — delivery registry used a domain status invalid for artifact metadata

- Location: `src/slidethus/mvp.py`
- Finding: `Delivery Manifest.status=ready` was incorrectly reused as registry artifact status, whose contract expects `draft/reviewed/approved/frozen/superseded`.
- Impact: the final delivery transaction rolled back at `REVIEWED`.
- Root phase: P9 application orchestration.
- Fix: keep the body status `ready` while publishing registry metadata as `approved`.
- Verification: end-to-end result reaches `DELIVERY_READY` and G9 passes.
- Status: fixed.

### ISS-MVP0-006 — Minor — independent previews were not recorded in Render Manifest

- Location: `src/slidethus/mvp.py`
- Finding: PNGs existed but lacked hashes and paths in the render fact source.
- Impact: preview provenance was weaker than output provenance.
- Root phase: P7 manifest construction.
- Fix: register every independent PNG as a hashed Render Manifest output.
- Verification: end-to-end test asserts one PPTX plus one PNG per slide; workspace hash validation passes.
- Status: fixed.

## Exit condition

- Open Critical: 0
- Open Major: 0
- Open Minor: 0
- Remaining limitations are declared MVP scope, not hidden defects.
