from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sysconfig
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from slidethus import __version__
from slidethus.constants import find_repository_root
from slidethus.errors import RenderCapabilityError, SlidethusError
from slidethus.io_utils import canonical_json_bytes, read_json, sha256_file
from slidethus.sbom import build_sbom
from slidethus.schema_registry import SchemaRegistry

_RENDERER_FILES = (
    "README.md",
    "package.json",
    "package-lock.json",
    "render.mjs",
    "preview.mjs",
)
_RENDERER_DEPENDENCIES = {
    "@resvg/resvg-js": "2.6.2",
    "pdf-lib": "1.17.1",
    "pptxgenjs": "4.0.1",
}
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_TASTE_SKILL_PATH = Path("providers/art-direction/taste/SKILL.md")
SKILL_NAMES = (
    "slidethus",
    "using-slidethus",
    "slidethus-brief",
    "slidethus-research",
    "slidethus-story",
    "slidethus-plan",
    "slidethus-design",
    "slidethus-render",
    "slidethus-review",
)


class DistributionError(SlidethusError):
    """Raised when Plugin/sidecar distribution cannot be materialized safely."""


@dataclass(frozen=True)
class PluginBundleResult:
    path: Path
    sha256: str
    file_count: int


@dataclass(frozen=True)
class RendererBootstrapResult:
    root: Path
    lock_sha256: str
    source_sha256: str
    dependency_sha256: str
    changed: bool


def installed_share_root() -> Path:
    return Path(sysconfig.get_path("data")).resolve() / "share/slidethus"


def _repository_root() -> Path | None:
    try:
        return find_repository_root().resolve()
    except FileNotFoundError:
        return None


def skill_source_root() -> Path:
    configured = os.environ.get("SLIDETHUS_SKILL_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        repository = _repository_root()
        root = (
            repository / ".agents/skills/slidethus"
            if repository is not None
            else installed_share_root() / "skills/slidethus"
        )
        if repository is None and not (root / "SKILL.md").is_file():
            root = installed_share_root() / "skill"
    if not (root / "SKILL.md").is_file():
        raise DistributionError(f"Slidethus Skill assets are unavailable: {root}")
    return root


def skill_source_roots() -> dict[str, Path]:
    """Resolve the complete allowlisted suite; never collect unrelated host skills."""

    legacy = skill_source_root()
    roots = {name: legacy if name == "slidethus" else legacy.parent / name for name in SKILL_NAMES}
    missing = [
        name for name, root in roots.items()
        if not (root / "SKILL.md").is_file() or not (root / "agents/openai.yaml").is_file()
    ]
    if missing:
        raise DistributionError("Slidethus Skill suite is incomplete: " + ", ".join(missing))
    return roots


def _skill_files(root: Path) -> dict[str, bytes]:
    if root.is_symlink() or any(path.is_symlink() for path in root.rglob("*")):
        raise DistributionError(f"Refusing symlinked Skill tree: {root}")
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def taste_skill_identity(source_root: Path | None = None) -> dict[str, Any]:
    """Return and verify the bundled default art-direction provider identity."""

    root = (source_root or skill_source_root()).resolve()
    skill_path = root / _TASTE_SKILL_PATH
    provenance_path = skill_path.parent / "PROVENANCE.json"
    license_path = skill_path.parent / "LICENSE"
    missing = [
        path.relative_to(root).as_posix()
        for path in (skill_path, provenance_path, license_path)
        if not path.is_file()
    ]
    if missing:
        raise DistributionError("Bundled Taste Skill is incomplete: " + ", ".join(missing))
    provenance = read_json(provenance_path)
    skill_sha = sha256_file(skill_path)
    license_sha = sha256_file(license_path)
    if provenance.get("files", {}).get("SKILL.md") != f"sha256:{skill_sha}":
        raise DistributionError("Bundled Taste Skill hash does not match provenance")
    if provenance.get("files", {}).get("LICENSE") != f"sha256:{license_sha}":
        raise DistributionError("Bundled Taste License hash does not match provenance")
    if provenance.get("license") != "MIT":
        raise DistributionError("Bundled Taste Skill must preserve its MIT license")
    return {
        "provider": "taste-skill",
        "version": str(provenance.get("upstream_commit", "")),
        "sha256": skill_sha,
        "license": "MIT",
        "path": _TASTE_SKILL_PATH.as_posix(),
    }


def renderer_source_root() -> Path:
    configured = os.environ.get("SLIDETHUS_RENDERER_SOURCE_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        repository = _repository_root()
        root = (
            repository / "renderers/pptxgenjs"
            if repository is not None
            else installed_share_root() / "renderer"
        )
    missing = [name for name in _RENDERER_FILES if not (root / name).is_file()]
    if missing:
        raise DistributionError(
            f"Slidethus renderer source is incomplete at {root}: {', '.join(missing)}"
        )
    return root


def release_source_files() -> dict[str, Path]:
    repository = _repository_root()
    if repository is not None:
        files = {
            "LICENSE": repository / "LICENSE",
            "NOTICE.md": repository / "NOTICE.md",
            "THIRD_PARTY_NOTICES.md": repository / "THIRD_PARTY_NOTICES.md",
            "release/rights-policy.json": repository / "release/rights-policy.json",
        }
    else:
        root = installed_share_root() / "release"
        files = {
            "LICENSE": root / "LICENSE",
            "NOTICE.md": root / "NOTICE.md",
            "THIRD_PARTY_NOTICES.md": root / "THIRD_PARTY_NOTICES.md",
            "release/rights-policy.json": root / "rights-policy.json",
        }
    missing = [name for name, path in files.items() if not path.is_file()]
    if missing:
        raise DistributionError("Slidethus release policy files are unavailable: " + ", ".join(missing))
    return files


def _cache_home(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    configured = os.environ.get("SLIDETHUS_CACHE_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return (base / "slidethus").resolve()


def renderer_lock_sha256(source_root: Path | None = None) -> str:
    root = (source_root or renderer_source_root()).resolve()
    return sha256_file(root / "package-lock.json")


def renderer_source_sha256(source_root: Path | None = None) -> str:
    root = (source_root or renderer_source_root()).resolve()
    digest = hashlib.sha256()
    for name in _RENDERER_FILES:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _dependency_tree_identity(root: Path) -> tuple[str, int]:
    node_modules = root / "node_modules"
    if not node_modules.is_dir():
        return "", 0
    admitted_root = node_modules.resolve()
    digest = hashlib.sha256()
    count = 0
    for path in sorted(node_modules.rglob("*")):
        relative = path.relative_to(node_modules).as_posix()
        if path.is_symlink():
            target = path.readlink()
            if target.is_absolute():
                return "", 0
            resolved = path.resolve()
            if not resolved.is_relative_to(admitted_root):
                return "", 0
            digest.update(b"symlink\0")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(target.as_posix().encode("utf-8"))
            digest.update(b"\0")
            count += 1
            continue
        if not path.is_file():
            continue
        digest.update(b"file\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        count += 1
    return digest.hexdigest(), count


def _dependency_manifest_path(root: Path) -> Path:
    return root / ".slidethus-dependencies.json"


def prepared_renderer_root(cache_home: Path | None = None) -> Path | None:
    try:
        source = renderer_source_root()
    except DistributionError:
        return None
    lock_sha = renderer_lock_sha256(source)
    source_sha = renderer_source_sha256(source)
    root = _cache_home(cache_home) / "renderer" / source_sha[:16]
    for name in _RENDERER_FILES:
        cached = root / name
        if not cached.is_file() or cached.read_bytes() != (source / name).read_bytes():
            return None
    if sha256_file(root / "package-lock.json") != lock_sha:
        return None
    for name, version in _RENDERER_DEPENDENCIES.items():
        package = root / "node_modules" / name / "package.json"
        if not package.is_file():
            return None
        try:
            if read_json(package).get("version") != version:
                return None
        except Exception:  # noqa: BLE001
            return None
    manifest_path = _dependency_manifest_path(root)
    if not manifest_path.is_file():
        return None
    try:
        manifest = read_json(manifest_path)
    except Exception:  # noqa: BLE001
        return None
    dependency_sha, dependency_files = _dependency_tree_identity(root)
    if not dependency_sha:
        return None
    if manifest != {
        "schema_version": "0.1.0",
        "renderer_source_sha256": source_sha,
        "renderer_lock_sha256": lock_sha,
        "dependency_tree_sha256": dependency_sha,
        "dependency_file_count": dependency_files,
    }:
        return None
    return root


def _validate_renderer_source(root: Path) -> None:
    package = read_json(root / "package.json")
    dependencies = package.get("dependencies", {})
    for name, version in _RENDERER_DEPENDENCIES.items():
        if dependencies.get(name) != version:
            raise DistributionError(
                f"Renderer package.json must pin {name}@{version}, got {dependencies.get(name)}"
            )
    lock = read_json(root / "package-lock.json")
    if int(lock.get("lockfileVersion", 0)) < 3:
        raise DistributionError("Renderer package-lock.json must use lockfileVersion >= 3")
    locked_root = lock.get("packages", {}).get("", {}).get("dependencies", {})
    for name, version in _RENDERER_DEPENDENCIES.items():
        if locked_root.get(name) != version:
            raise DistributionError(
                f"Renderer package-lock root must pin {name}@{version}, got {locked_root.get(name)}"
            )


def bootstrap_renderer(
    *,
    cache_home: Path | None = None,
    npm: str | None = None,
    node: str | None = None,
) -> RendererBootstrapResult:
    """Materialize the pinned Node sidecar into user cache and install exact dependencies."""

    source = renderer_source_root()
    _validate_renderer_source(source)
    lock_sha = renderer_lock_sha256(source)
    source_sha = renderer_source_sha256(source)
    target = _cache_home(cache_home) / "renderer" / source_sha[:16]
    existing = prepared_renderer_root(cache_home)
    if existing is not None and existing == target:
        dependency_sha, _dependency_files = _dependency_tree_identity(target)
        return RendererBootstrapResult(
            root=target,
            lock_sha256=lock_sha,
            source_sha256=source_sha,
            dependency_sha256=dependency_sha,
            changed=False,
        )

    target.mkdir(parents=True, exist_ok=True)
    for name in _RENDERER_FILES:
        shutil.copy2(source / name, target / name)
    dependency_root = target / "node_modules"
    if dependency_root.exists():
        shutil.rmtree(dependency_root)
    dependency_manifest_path = _dependency_manifest_path(target)
    if dependency_manifest_path.exists():
        dependency_manifest_path.unlink()

    from slidethus.render_backends.node_toolchain import node_executable, validate_sidecar

    node_executable(node)
    npm_executable = npm or os.environ.get("SLIDETHUS_NPM") or shutil.which("npm")
    if not npm_executable:
        raise RenderCapabilityError("Renderer bootstrap requires npm")
    version = subprocess.run(
        [npm_executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if version.returncode != 0:
        raise RenderCapabilityError("npm version check failed")
    try:
        npm_major = int(version.stdout.strip().split(".", 1)[0])
    except ValueError as exc:
        raise RenderCapabilityError(
            f"Cannot parse npm version: {version.stdout.strip()}"
        ) from exc
    if npm_major < 9:
        raise RenderCapabilityError(
            f"Renderer bootstrap requires npm >=9, got {version.stdout.strip()}"
        )
    process = subprocess.run(
        [
            npm_executable,
            "ci",
            "--omit=dev",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
        ],
        cwd=target,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if process.returncode != 0:
        detail = (process.stderr or process.stdout).strip()
        raise RenderCapabilityError(
            f"Renderer bootstrap npm ci failed: {detail or process.returncode}"
        )
    validate_sidecar(
        target,
        script_name="render.mjs",
        dependencies={"pptxgenjs": _RENDERER_DEPENDENCIES["pptxgenjs"]},
    )
    validate_sidecar(
        target,
        script_name="preview.mjs",
        dependencies={
            "@resvg/resvg-js": _RENDERER_DEPENDENCIES["@resvg/resvg-js"],
            "pdf-lib": _RENDERER_DEPENDENCIES["pdf-lib"],
        },
    )
    dependency_sha, dependency_files = _dependency_tree_identity(target)
    if not dependency_sha:
        raise RenderCapabilityError("Renderer bootstrap produced an invalid dependency tree")
    dependency_manifest = {
        "schema_version": "0.1.0",
        "renderer_source_sha256": source_sha,
        "renderer_lock_sha256": lock_sha,
        "dependency_tree_sha256": dependency_sha,
        "dependency_file_count": dependency_files,
    }
    manifest_path = _dependency_manifest_path(target)
    manifest_path.write_bytes(canonical_json_bytes(dependency_manifest) + b"\n")
    if prepared_renderer_root(cache_home) != target:
        raise RenderCapabilityError("Renderer bootstrap completed but prepared cache verification failed")
    return RendererBootstrapResult(
        root=target,
        lock_sha256=lock_sha,
        source_sha256=source_sha,
        dependency_sha256=dependency_sha,
        changed=True,
    )


def materialize_skill(destination_root: Path) -> Path:
    """Install the suite after conflict preflight; return the legacy Skill root."""

    sources = skill_source_roots()
    source_files = {name: _skill_files(source) for name, source in sources.items()}
    parent = destination_root.expanduser().resolve() / ".agents/skills"
    for path in (parent.parent, parent):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise DistributionError(f"Refusing non-directory or symlinked Skill destination: {path}")
    for name in SKILL_NAMES:
        destination = parent / name
        if destination.is_symlink():
            raise DistributionError(f"Refusing symlinked Skill tree: {destination}")
        if not destination.exists():
            continue
        existing = _skill_files(destination)
        if not destination.is_dir() or existing.keys() != source_files[name].keys():
            raise DistributionError(
                f"Refusing to replace a non-matching existing Slidethus Skill tree: {destination}"
            )
        for relative, payload in source_files[name].items():
            if existing[relative] != payload:
                raise DistributionError(
                    f"Refusing to overwrite modified Skill file: {destination / relative}"
                )
    # No destination is written until every existing module has passed preflight.
    for name, source in sources.items():
        destination = parent / name
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination)
    return parent / "slidethus"


def plugin_manifest_identity_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data)
    payload.pop("manifest_id", None)
    return payload


def plugin_manifest_id(data: dict[str, Any]) -> str:
    return "PLG-" + hashlib.sha256(
        canonical_json_bytes(plugin_manifest_identity_payload(data))
    ).hexdigest()[:16].upper()


def validate_plugin_manifest(data: dict[str, Any], schema_dir: Path) -> tuple[str, ...]:
    schema_path = schema_dir / "plugin_manifest.schema.json"
    if not schema_path.is_file():
        return (f"Plugin Manifest schema is missing: {schema_path}",)
    schema = read_json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in sorted(
            Draft202012Validator(schema).iter_errors(data),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors:
        return tuple(errors)
    if data.get("manifest_id") != plugin_manifest_id(data):
        errors.append("Plugin Manifest identity mismatch")
    paths = [str(item.get("path", "")) for item in data.get("files", [])]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        errors.append("Plugin Manifest file paths must be sorted and unique")
    for raw in paths:
        path = Path(raw)
        if path.is_absolute() or ".." in path.parts:
            errors.append(f"Plugin Manifest contains unsafe path: {raw}")
    return tuple(errors)


def _zip_bytes(files: dict[str, bytes], manifest: dict[str, Any]) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        payloads = {**files, "plugin-manifest.json": canonical_json_bytes(manifest) + b"\n"}
        for name in sorted(payloads):
            info = zipfile.ZipInfo(name, _FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payloads[name])
    return buffer.getvalue()


def build_plugin_bundle(output_path: Path) -> PluginBundleResult:
    """Build one deterministic Plugin zip from canonical/installed distribution assets."""

    skills = skill_source_roots()
    taste = taste_skill_identity(skills["slidethus"])
    renderer = renderer_source_root()
    schemas = SchemaRegistry().schema_dir
    files: dict[str, bytes] = {}
    for name, skill in skills.items():
        for relative, payload in _skill_files(skill).items():
            files[f".agents/skills/{name}/{relative}"] = payload
    for name in _RENDERER_FILES:
        files[f"renderers/pptxgenjs/{name}"] = (renderer / name).read_bytes()
    for path in sorted(schemas.glob("*.json")):
        files[f"schemas/{path.name}"] = path.read_bytes()
    for name, path in release_source_files().items():
        files[name] = path.read_bytes()
    sbom_root = _repository_root() or installed_share_root()
    files["release/sbom.spdx.json"] = canonical_json_bytes(build_sbom(sbom_root)) + b"\n"
    manifest: dict[str, Any] = {
        "schema_version": "0.1.0",
        "manifest_id": "",
        "plugin": "slidethus",
        "version": __version__,
        "requirements": {
            "python": ">=3.11",
            "node": ">=20",
            "renderer_lock_sha256": renderer_lock_sha256(renderer),
            "renderer_source_sha256": renderer_source_sha256(renderer),
            "default_art_direction_provider": taste["provider"],
            "art_direction_provider_sha256": taste["sha256"],
        },
        "files": [
            {"path": name, "sha256": hashlib.sha256(payload).hexdigest()}
            for name, payload in sorted(files.items())
        ],
    }
    manifest["manifest_id"] = plugin_manifest_id(manifest)
    manifest_errors = validate_plugin_manifest(manifest, schemas)
    if manifest_errors:
        raise DistributionError(
            "Invalid Plugin Manifest: " + "; ".join(manifest_errors)
        )
    payload = _zip_bytes(files, manifest)
    output = output_path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if not output.is_file() or output.read_bytes() != payload:
            raise DistributionError(
                f"Refusing to overwrite a different existing Plugin bundle: {output}"
            )
    else:
        output.write_bytes(payload)
    return PluginBundleResult(
        path=output,
        sha256=hashlib.sha256(payload).hexdigest(),
        file_count=len(files) + 1,
    )


def distribution_status() -> dict[str, Any]:
    skills = skill_source_roots()
    taste = taste_skill_identity(skills["slidethus"])
    renderer = renderer_source_root()
    prepared = prepared_renderer_root()
    return {
        "version": __version__,
        "skill_root": str(skills["slidethus"]),
        "entry_skill_root": str(skills["using-slidethus"]),
        "skill_roots": {name: str(path) for name, path in skills.items()},
        "default_art_direction_provider": taste,
        "renderer_source_root": str(renderer),
        "renderer_lock_sha256": renderer_lock_sha256(renderer),
        "renderer_source_sha256": renderer_source_sha256(renderer),
        "prepared_renderer_root": str(prepared) if prepared is not None else None,
        "renderer_prepared": prepared is not None,
    }
