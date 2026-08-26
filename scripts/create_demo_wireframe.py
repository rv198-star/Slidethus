from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slidethus.constants import find_repository_root
from slidethus.wireframe import render_wireframes


def main() -> int:
    root = find_repository_root()
    outputs = render_wireframes(root / "examples/minimal_project")
    for output in outputs:
        print(output.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
