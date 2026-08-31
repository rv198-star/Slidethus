from __future__ import annotations

import hashlib
import json
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

from slidethus.constants import find_repository_root
from slidethus.distribution import (
    SKILL_NAMES,
    bootstrap_renderer,
    build_plugin_bundle,
    materialize_skill,
    validate_plugin_manifest,
)
from slidethus.schema_registry import SchemaRegistry


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _fake_node(root: Path) -> Path:
    path = root / "node"
    path.write_text("#!/bin/sh\nprintf 'v22.0.0\\n'\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_npm(root: Path) -> Path:
    path = root / "npm"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "if '--version' in sys.argv:\n"
        "    print('10.9.8')\n"
        "    raise SystemExit(0)\n"
        "versions = {'pptxgenjs': '4.0.1', '@resvg/resvg-js': '2.6.2', 'pdf-lib': '1.17.1'}\n"
        "root = pathlib.Path.cwd() / 'node_modules'\n"
        "for name, version in versions.items():\n"
        "    target = root / name / 'package.json'\n"
        "    target.parent.mkdir(parents=True, exist_ok=True)\n"
        "    target.write_text(json.dumps({'name': name, 'version': version}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def evaluate(root: Path) -> tuple[Check, ...]:
    checks: list[Check] = []
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    data_files = pyproject["tool"]["setuptools"]["data-files"]
    configured = {
        item
        for values in data_files.values()
        for item in values
    }
    expected_skill = {
        path.relative_to(root).as_posix()
        for name in SKILL_NAMES
        for path in (root / ".agents/skills" / name).rglob("*")
        if path.is_file()
    }
    configured_skill = {item for item in configured if item.startswith(".agents/skills/")}
    checks.append(
        Check(
            "wheel_skill_assets",
            configured_skill == expected_skill,
            f"wheel data-files cover all {len(expected_skill)} canonical Skill suite files"
            if configured_skill == expected_skill
            else f"missing={sorted(expected_skill - configured_skill)} extra={sorted(configured_skill - expected_skill)}",
        )
    )
    expected_renderer = {
        f"renderers/pptxgenjs/{name}"
        for name in ("README.md", "package.json", "package-lock.json", "render.mjs", "preview.mjs")
    }
    configured_renderer = {item for item in configured if item.startswith("renderers/pptxgenjs/")}
    checks.append(
        Check(
            "wheel_renderer_assets",
            configured_renderer == expected_renderer,
            "wheel data-files contain the complete runtime renderer source"
            if configured_renderer == expected_renderer
            else f"renderer data-file mismatch: {sorted(configured_renderer ^ expected_renderer)}",
        )
    )
    source_schema = root / "schemas/plugin_manifest.schema.json"
    packaged_schema = root / "src/slidethus/_schemas/plugin_manifest.schema.json"
    checks.append(
        Check(
            "plugin_schema_mirror",
            source_schema.is_file()
            and packaged_schema.is_file()
            and source_schema.read_bytes() == packaged_schema.read_bytes(),
            "Plugin Manifest schema is packaged without mirror drift",
        )
    )

    with tempfile.TemporaryDirectory(prefix="slidethus-m6-3-") as name:
        temporary = Path(name)
        first = build_plugin_bundle(temporary / "first.zip")
        second = build_plugin_bundle(temporary / "second.zip")
        reproducible = first.sha256 == second.sha256 and first.path.read_bytes() == second.path.read_bytes()
        checks.append(
            Check(
                "plugin_bundle_reproducible",
                reproducible,
                f"deterministic Plugin zip sha256={first.sha256}" if reproducible else "Plugin zip bytes drift",
            )
        )
        with zipfile.ZipFile(first.path) as archive:
            manifest = json.loads(archive.read("plugin-manifest.json"))
            errors = validate_plugin_manifest(manifest, SchemaRegistry().schema_dir)
            hash_errors = [
                entry["path"]
                for entry in manifest.get("files", [])
                if hashlib.sha256(archive.read(entry["path"])).hexdigest() != entry["sha256"]
            ]
        checks.append(
            Check(
                "plugin_manifest_lineage",
                not errors and not hash_errors,
                "Plugin Manifest schema, identity and file hashes are valid"
                if not errors and not hash_errors
                else "; ".join([*errors, *(f"hash:{item}" for item in hash_errors)]),
            )
        )

        installed = materialize_skill(temporary / "host")
        skill_ok = (installed / "SKILL.md").is_file() and all(
            (installed.parent / path.relative_to(root / ".agents/skills")).read_bytes()
            == path.read_bytes()
            for name in SKILL_NAMES
            for path in (root / ".agents/skills" / name).rglob("*")
            if path.is_file()
        )
        checks.append(
            Check(
                "skill_materialization",
                skill_ok,
                "complete Skill suite materializes byte-identically" if skill_ok else "Skill materialization drift",
            )
        )

        cache = temporary / "cache"
        bootstrap_first = bootstrap_renderer(
            cache_home=cache,
            npm=str(_fake_npm(temporary)),
            node=str(_fake_node(temporary)),
        )
        bootstrap_second = bootstrap_renderer(
            cache_home=cache,
            npm=str(temporary / "npm"),
            node=str(temporary / "node"),
        )
        bootstrap_ok = (
            bootstrap_first.changed
            and not bootstrap_second.changed
            and bootstrap_first.root == bootstrap_second.root
            and bootstrap_first.source_sha256 == bootstrap_second.source_sha256
        )
        checks.append(
            Check(
                "renderer_bootstrap",
                bootstrap_ok,
                "renderer source is content-addressed, version-checked and bootstrap-idempotent"
                if bootstrap_ok
                else "renderer bootstrap is not idempotent",
            )
        )
    return tuple(checks)


def main() -> int:
    checks = evaluate(find_repository_root())
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    passed = sum(check.ok for check in checks)
    print(f"M6.3 DISTRIBUTION: {passed}/{len(checks)} checks passed")
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
