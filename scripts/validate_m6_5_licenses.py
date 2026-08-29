from __future__ import annotations

import json
import sys
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slidethus.constants import find_repository_root
from slidethus.distribution import build_plugin_bundle
from slidethus.io_utils import read_json
from slidethus.sbom import build_sbom, validate_sbom


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def evaluate_m6_5(root: Path) -> tuple[Check, ...]:
    root = root.resolve()
    checks: list[Check] = []

    license_path = root / "LICENSE"
    license_text = license_path.read_text(encoding="utf-8") if license_path.is_file() else ""
    license_ok = (
        "Apache License" in license_text
        and "Version 2.0, January 2004" in license_text
        and "END OF TERMS AND CONDITIONS" in license_text
    )
    checks.append(
        Check(
            "project_license",
            license_ok,
            "Apache-2.0 license text is present"
            if license_ok
            else "Apache-2.0 LICENSE is missing or incomplete",
        )
    )

    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project", {})
    pyproject_ok = (
        project.get("license") == "Apache-2.0"
        and {"LICENSE", "NOTICE.md", "THIRD_PARTY_NOTICES.md"}.issubset(
            set(project.get("license-files", []))
        )
    )
    checks.append(
        Check(
            "package_license_metadata",
            pyproject_ok,
            "pyproject declares Apache-2.0 and ships license/notice files"
            if pyproject_ok
            else "pyproject license metadata is incomplete",
        )
    )

    notice = (root / "NOTICE.md").read_text(encoding="utf-8") if (root / "NOTICE.md").is_file() else ""
    third = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8") if (root / "THIRD_PARTY_NOTICES.md").is_file() else ""
    notices_ok = (
        "Apache License, Version 2.0" in notice
        and "source_material/" in notice
        and "@resvg/resvg-js" in third
        and "MPL-2.0" in third
        and "python-pptx" in third
        and "prepared renderer cache" in third
    )
    checks.append(
        Check(
            "notices",
            notices_ok,
            "NOTICE and THIRD_PARTY_NOTICES preserve project/source/dependency boundaries"
            if notices_ok
            else "notice/third-party boundary is incomplete",
        )
    )

    source_boundary = root / "source_material/LICENSE.md"
    source_ok = source_boundary.is_file() and "not licensed under the Slidethus Apache-2.0" in source_boundary.read_text(encoding="utf-8")
    data_files = pyproject.get("tool", {}).get("setuptools", {}).get("data-files", {})
    distributed_paths = [item for values in data_files.values() for item in values]
    source_excluded = all(not str(item).startswith("source_material/") for item in distributed_paths)
    checks.append(
        Check(
            "source_material_exclusion",
            source_ok and source_excluded,
            "source_material has an explicit no-relicense boundary and is excluded from wheel data-files"
            if source_ok and source_excluded
            else "source_material release exclusion is incomplete",
        )
    )

    schema_path = root / "schemas/release_rights_policy.schema.json"
    mirror_path = root / "src/slidethus/_schemas/release_rights_policy.schema.json"
    rights_path = root / "release/rights-policy.json"
    rights_errors: list[str] = []
    try:
        schema = read_json(schema_path)
        Draft202012Validator.check_schema(schema)
        rights = read_json(rights_path)
        rights_errors.extend(
            error.message for error in Draft202012Validator(schema).iter_errors(rights)
        )
    except Exception as exc:  # noqa: BLE001
        rights_errors.append(str(exc))
    if schema_path.is_file() and mirror_path.is_file() and schema_path.read_bytes() != mirror_path.read_bytes():
        rights_errors.append("schema mirror drift")
    checks.append(
        Check(
            "rights_policy",
            not rights_errors,
            "release rights policy is schema-valid and packaged mirror matches"
            if not rights_errors
            else "; ".join(rights_errors),
        )
    )

    sbom = build_sbom(root)
    sbom_errors = validate_sbom(root, sbom)
    npm_packages = [item for item in sbom.get("packages", []) if str(item.get("SPDXID", "")).startswith("SPDXRef-NPM-")]
    python_packages = [item for item in sbom.get("packages", []) if str(item.get("SPDXID", "")).startswith("SPDXRef-PyPI-")]
    sbom_ok = not sbom_errors and len(npm_packages) >= 20 and len(python_packages) == 6
    checks.append(
        Check(
            "spdx_sbom",
            sbom_ok,
            f"deterministic SPDX 2.3 covers {len(python_packages)} Python direct and {len(npm_packages)} exact Node packages"
            if sbom_ok
            else "; ".join(sbom_errors) or f"unexpected package counts: python={len(python_packages)} npm={len(npm_packages)}",
        )
    )

    with tempfile.TemporaryDirectory(prefix="slidethus-m6-5-") as directory:
        bundle = build_plugin_bundle(Path(directory) / "plugin.zip")
        with zipfile.ZipFile(bundle.path) as archive:
            names = set(archive.namelist())
            required = {
                "LICENSE",
                "NOTICE.md",
                "THIRD_PARTY_NOTICES.md",
                "release/rights-policy.json",
                "release/sbom.spdx.json",
            }
            forbidden = any(
                name.startswith("source_material/")
                or "node_modules/" in name
                or name.lower().endswith((".ttf", ".otf", ".woff", ".woff2"))
                for name in names
            )
            embedded_sbom = json.loads(archive.read("release/sbom.spdx.json"))
            plugin_ok = required.issubset(names) and not forbidden and not validate_sbom(root, embedded_sbom)
    checks.append(
        Check(
            "plugin_rights_boundary",
            plugin_ok,
            "Plugin embeds license/notices/rights/SBOM while excluding source material, node_modules and font binaries"
            if plugin_ok
            else "Plugin rights boundary is incomplete",
        )
    )

    return tuple(checks)


def main() -> int:
    checks = evaluate_m6_5(find_repository_root())
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    passed = sum(check.ok for check in checks)
    print(f"M6.5 LICENSES: {passed}/{len(checks)} checks passed")
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
