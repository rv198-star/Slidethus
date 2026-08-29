from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slidethus.constants import find_repository_root
from slidethus.sbom import build_sbom, validate_sbom


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate or verify the Slidethus source-distribution SPDX SBOM"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = find_repository_root()
    target = (args.output or root / "release/sbom.spdx.json").resolve()
    if args.check:
        if not target.is_file():
            print(f"FAIL: SBOM is missing: {target}")
            return 1
        current = json.loads(target.read_text(encoding="utf-8"))
        errors = validate_sbom(root, current)
        if errors:
            for error in errors:
                print(f"FAIL: {error}")
            return 1
        print(f"PASS: SPDX SBOM matches release inputs ({len(current['packages'])} packages)")
        return 0
    sbom = build_sbom(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(sbom, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
