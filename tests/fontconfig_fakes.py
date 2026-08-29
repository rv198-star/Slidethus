from __future__ import annotations

import shlex
from pathlib import Path


def write_fontconfig_tools(
    tmp_path: Path,
    *,
    charset: str = "20-10ffff",
) -> Path:
    """Create deterministic fc-match/fc-query fakes with declared charset coverage."""

    font = tmp_path / "test.ttf"
    font.write_bytes(b"fontconfig-test-placeholder")
    matcher = tmp_path / "fc-match"
    matcher.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n%s\\n' \"$3\" {shlex.quote(str(font))}\n",
        encoding="utf-8",
    )
    matcher.chmod(0o755)
    query = tmp_path / "fc-query"
    query.write_text(
        f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(charset)}\n",
        encoding="utf-8",
    )
    query.chmod(0o755)
    return matcher
