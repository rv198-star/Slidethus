from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from slidethus.artifact_runtime import ArtifactRuntime
from slidethus.errors import FontResolutionError, RenderAssetError
from slidethus.io_utils import sha256_file
from slidethus.services.font_resolution import FontResolutionService
from slidethus.services.render_assets import RenderAssetService, validate_safe_svg
from slidethus.workspace import init_workspace


def _asset_workspace(tmp_path: Path) -> tuple[Path, ArtifactRuntime]:
    workspace = init_workspace(tmp_path / "workspace", title="Render Assets")
    return workspace, ArtifactRuntime(workspace)


def _write_manifest(runtime: ArtifactRuntime, assets: list[dict]) -> None:
    manifest, version = runtime.read_artifact_snapshot("asset_manifest")
    manifest["assets"] = assets
    runtime.write_artifact(
        "asset_manifest",
        manifest,
        expected_version=version,
        status="approved",
        created_by="render-assets-test",
    )


def test_raster_asset_is_hash_and_dimension_verified(tmp_path: Path) -> None:
    workspace, runtime = _asset_workspace(tmp_path)
    path = workspace / "assets/photo.png"
    Image.new("RGB", (64, 32), (255, 255, 255)).save(path)
    _write_manifest(
        runtime,
        [
            {
                "asset_id": "AST-001",
                "kind": "image",
                "source_type": "user_provided",
                "path_or_url": "assets/photo.png",
                "license": "user-owned",
                "allowed_use": "full",
                "content_hash": "sha256:" + sha256_file(path),
                "media_type": "image/png",
                "width": 64,
                "height": 32,
                "dpi": None,
                "alt_text": "White test image",
                "fit": "contain",
                "editable_as": "raster",
                "status": "available",
                "notes": [],
            }
        ],
    )

    asset = RenderAssetService(workspace).resolve(("AST-001",))["AST-001"]

    assert asset.path == path
    assert asset.width == 64
    assert asset.height == 32
    assert asset.media_type == "image/png"


def test_svg_asset_rejects_active_content_and_external_references(tmp_path: Path) -> None:
    active = tmp_path / "active.svg"
    active.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        encoding="utf-8",
    )
    external = tmp_path / "external.svg"
    external.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/a.png"/></svg>',
        encoding="utf-8",
    )
    safe = tmp_path / "safe.svg"
    safe.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>',
        encoding="utf-8",
    )

    with pytest.raises(RenderAssetError, match="element"):
        validate_safe_svg(active)
    with pytest.raises(RenderAssetError, match="external reference"):
        validate_safe_svg(external)
    validate_safe_svg(safe)


def test_table_data_asset_loads_bounded_csv_without_formula_execution(tmp_path: Path) -> None:
    workspace, runtime = _asset_workspace(tmp_path)
    path = workspace / "assets/table.csv"
    path.write_text("name,value\nA,=1+1\nB,4\n", encoding="utf-8")
    _write_manifest(
        runtime,
        [
            {
                "asset_id": "AST-001",
                "kind": "table_data",
                "source_type": "user_provided",
                "path_or_url": "assets/table.csv",
                "license": "user-owned",
                "allowed_use": "full",
                "content_hash": sha256_file(path),
                "media_type": "text/csv",
                "fit": "none",
                "editable_as": "data",
                "data_contract": {
                    "format": "csv",
                    "delimiter": ",",
                    "has_header": True,
                },
                "status": "available",
                "notes": [],
            }
        ],
    )

    rows = RenderAssetService(workspace).load_data("AST-001")

    assert rows == [["name", "value"], ["A", "=1+1"], ["B", "4"]]


def test_font_resolution_uses_declared_fallback(tmp_path: Path) -> None:
    primary_font = tmp_path / "primary.ttf"
    fallback_font = tmp_path / "fallback.ttf"
    primary_font.write_bytes(b"primary")
    fallback_font.write_bytes(b"fallback")
    matcher = tmp_path / "fc-match"
    matcher.write_text(
        "#!/bin/sh\n"
        "case \"$3\" in\n"
        f"  Missing*) printf 'DejaVu Sans\\n{primary_font}\\n' ;;\n"
        f"  Fallback*) printf 'Fallback Sans\\n{fallback_font}\\n' ;;\n"
        f"  *) printf 'DejaVu Sans\\n{primary_font}\\n' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    matcher.chmod(0o755)
    query = tmp_path / "fc-query"
    query.write_text(
        "#!/bin/sh\n"
        "case \"$3\" in\n"
        f"  {fallback_font}) printf '20-7e 400-4ff\\n' ;;\n"
        "  *) printf '20-7e\\n' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    query.chmod(0o755)
    service = FontResolutionService(
        font_match=str(matcher),
        font_query=str(query),
    )

    resolution = service.resolve_family(
        "Missing Sans",
        fallbacks=("Fallback Sans",),
        required_characters="Decision Ж",
    )

    assert resolution.requested == "Missing Sans"
    assert resolution.actual == "Fallback Sans"
    assert resolution.status == "substituted"
    assert resolution.reason == "fallback_selected:Fallback Sans:glyph_coverage_verified"


def test_font_resolution_blocks_when_no_candidate_covers_required_glyphs(
    tmp_path: Path,
) -> None:
    font = tmp_path / "latin-only.ttf"
    font.write_bytes(b"latin")
    matcher = tmp_path / "fc-match"
    matcher.write_text(
        f"#!/bin/sh\nprintf '%s\\n{font}\\n' \"$3\"\n",
        encoding="utf-8",
    )
    matcher.chmod(0o755)
    query = tmp_path / "fc-query"
    query.write_text("#!/bin/sh\nprintf '20-7e\\n'\n", encoding="utf-8")
    query.chmod(0o755)
    service = FontResolutionService(
        font_match=str(matcher),
        font_query=str(query),
    )

    with pytest.raises(FontResolutionError, match=r"U\+4E2D"):
        service.resolve_family("Latin Only", required_characters="English 中文")
