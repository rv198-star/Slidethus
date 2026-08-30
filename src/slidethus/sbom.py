from __future__ import annotations

import hashlib
import importlib.metadata
import re
import tomllib
from pathlib import Path
from typing import Any

from slidethus import __version__
from slidethus.io_utils import canonical_json_bytes, read_json

_CREATED = "2026-08-29T00:00:00Z"
_PYTHON_LICENSES = {
    "jsonschema": "MIT",
    "python-pptx": "MIT",
    "pypdf": "BSD-3-Clause",
    "python-docx": "MIT",
    "openpyxl": "MIT",
    "Pillow": "MIT-CMU",
}


def _spdx_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    safe = re.sub(r"[^A-Za-z0-9.-]+", "-", prefix).strip("-") or "Package"
    return f"SPDXRef-{safe}-{digest}"


def _python_requirements(root: Path) -> list[str]:
    pyproject_path = root / "pyproject.toml"
    if pyproject_path.is_file():
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project = pyproject["project"]
        requirements: list[str] = list(project.get("dependencies", []))
        requirements.extend(project.get("optional-dependencies", {}).get("ingestion", []))
        return requirements
    requirements = []
    for raw in importlib.metadata.requires("slidethus") or []:
        lowered = raw.lower()
        if "extra == \"dev\"" in lowered or "extra == 'dev'" in lowered:
            continue
        requirements.append(raw.split(";", 1)[0].strip())
    return requirements


def _python_dependencies(root: Path) -> list[dict[str, Any]]:
    requirements = _python_requirements(root)
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for requirement in requirements:
        match = re.match(r"^([A-Za-z0-9_.-]+)(.*)$", requirement.strip())
        if match is None:
            continue
        name = match.group(1)
        constraint = match.group(2).strip() or "NOASSERTION"
        normalized = name.lower().replace("_", "-")
        if normalized in seen:
            continue
        seen.add(normalized)
        license_id = _PYTHON_LICENSES.get(name, _PYTHON_LICENSES.get(normalized, "NOASSERTION"))
        output.append(
            {
                "name": name,
                "SPDXID": _spdx_id("PyPI", f"{normalized}:{constraint}"),
                "versionInfo": constraint,
                "downloadLocation": f"https://pypi.org/project/{name}/",
                "filesAnalyzed": False,
                "licenseConcluded": license_id,
                "licenseDeclared": license_id,
                "copyrightText": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:pypi/{normalized}",
                    }
                ],
                "comment": "Direct Slidethus Python dependency constraint; exact resolved version belongs in an artifact/environment-specific SBOM.",
            }
        )
    return sorted(output, key=lambda item: item["name"].lower())


def _node_name(path: str) -> str:
    value = path.removeprefix("node_modules/")
    if "/node_modules/" in value:
        value = value.rsplit("/node_modules/", 1)[1]
    return value


def _renderer_root(root: Path) -> Path:
    repository_renderer = root / "renderers/pptxgenjs"
    if (repository_renderer / "package-lock.json").is_file():
        return repository_renderer
    installed_renderer = root / "renderer"
    if (installed_renderer / "package-lock.json").is_file():
        return installed_renderer
    raise FileNotFoundError(f"Cannot locate Slidethus renderer lock under {root}")


def _node_dependencies(root: Path) -> list[dict[str, Any]]:
    lock = read_json(_renderer_root(root) / "package-lock.json")
    output: list[dict[str, Any]] = []
    for path, entry in sorted(lock.get("packages", {}).items()):
        if not path or not path.startswith("node_modules/"):
            continue
        name = _node_name(path)
        version = str(entry.get("version", ""))
        if not version:
            continue
        license_id = str(entry.get("license") or "NOASSERTION")
        resolved = str(entry.get("resolved") or "NOASSERTION")
        package: dict[str, Any] = {
            "name": name,
            "SPDXID": _spdx_id("NPM", f"{name}@{version}:{path}"),
            "versionInfo": version,
            "downloadLocation": resolved,
            "filesAnalyzed": False,
            "licenseConcluded": license_id,
            "licenseDeclared": license_id,
            "copyrightText": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:npm/{name.replace('@', '%40')}@{version}",
                }
            ],
        }
        integrity = entry.get("integrity")
        if integrity:
            package["comment"] = f"package-lock integrity: {integrity}"
        output.append(package)
    return output


def _taste_package(root: Path) -> dict[str, Any]:
    repository = root / ".agents/skills/slidethus/providers/art-direction/taste"
    installed = root / "skill/providers/art-direction/taste"
    taste_root = repository if (repository / "PROVENANCE.json").is_file() else installed
    provenance = read_json(taste_root / "PROVENANCE.json")
    commit = str(provenance["upstream_commit"])
    return {
        "name": "taste-skill",
        "SPDXID": _spdx_id("GitHub", f"Leonxlnx/taste-skill@{commit}"),
        "versionInfo": commit,
        "downloadLocation": str(provenance["upstream_url"]),
        "filesAnalyzed": False,
        "licenseConcluded": "MIT",
        "licenseDeclared": "MIT",
        "copyrightText": str(provenance["copyright"]),
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": f"pkg:github/Leonxlnx/taste-skill@{commit}",
            }
        ],
        "comment": "Bundled default art-direction Skill; original MIT license and provenance are preserved.",
    }


def build_sbom(root: Path) -> dict[str, Any]:
    root = root.resolve()
    project_id = "SPDXRef-Package-Slidethus"
    renderer_id = "SPDXRef-Package-Slidethus-Renderer"
    python_packages = _python_dependencies(root)
    node_packages = _node_dependencies(root)
    taste_package = _taste_package(root)
    packages: list[dict[str, Any]] = [
        {
            "name": "slidethus",
            "SPDXID": project_id,
            "versionInfo": __version__,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "Apache-2.0",
            "licenseDeclared": "Apache-2.0",
            "copyrightText": "Copyright 2026 Slidethus contributors",
        },
        {
            "name": "@slidethus/pptxgenjs-renderer",
            "SPDXID": renderer_id,
            "versionInfo": str(read_json(_renderer_root(root) / "package.json")["version"]),
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "Apache-2.0",
            "licenseDeclared": "Apache-2.0",
            "copyrightText": "Copyright 2026 Slidethus contributors",
        },
        taste_package,
        *python_packages,
        *node_packages,
    ]
    relationships: list[dict[str, str]] = [
        {
            "spdxElementId": project_id,
            "relationshipType": "CONTAINS",
            "relatedSpdxElement": renderer_id,
        },
        {
            "spdxElementId": project_id,
            "relationshipType": "CONTAINS",
            "relatedSpdxElement": taste_package["SPDXID"],
        },
    ]
    relationships.extend(
        {
            "spdxElementId": project_id,
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": item["SPDXID"],
        }
        for item in python_packages
    )
    relationships.extend(
        {
            "spdxElementId": renderer_id,
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": item["SPDXID"],
        }
        for item in node_packages
    )
    identity_payload = {
        "version": __version__,
        "packages": [
            (item["name"], item.get("versionInfo"), item.get("licenseDeclared"))
            for item in packages
        ],
    }
    namespace_hash = hashlib.sha256(canonical_json_bytes(identity_payload)).hexdigest()
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"Slidethus-{__version__}-source-distribution",
        "documentNamespace": f"https://slidethus.dev/spdx/{__version__}/{namespace_hash}",
        "creationInfo": {
            "created": _CREATED,
            "creators": ["Tool: Slidethus SPDX builder"],
        },
        "documentDescribes": [project_id],
        "packages": packages,
        "relationships": relationships,
    }


def validate_sbom(root: Path, sbom: dict[str, Any]) -> tuple[str, ...]:
    errors: list[str] = []
    if sbom != build_sbom(root):
        errors.append("SPDX SBOM does not match pyproject/package-lock release inputs")
    if sbom.get("spdxVersion") != "SPDX-2.3" or sbom.get("dataLicense") != "CC0-1.0":
        errors.append("SPDX document header is invalid")
    ids = [str(item.get("SPDXID", "")) for item in sbom.get("packages", [])]
    if len(ids) != len(set(ids)):
        errors.append("SPDX package IDs are not unique")
    if not any(
        item.get("name") == "@resvg/resvg-js"
        and item.get("licenseDeclared") == "MPL-2.0"
        for item in sbom.get("packages", [])
    ):
        errors.append("SPDX SBOM does not preserve @resvg/resvg-js MPL-2.0 declaration")
    if not any(
        item.get("name") == "taste-skill"
        and item.get("licenseDeclared") == "MIT"
        for item in sbom.get("packages", [])
    ):
        errors.append("SPDX SBOM does not preserve bundled Taste Skill MIT declaration")
    return tuple(errors)
