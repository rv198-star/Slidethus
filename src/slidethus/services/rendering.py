from __future__ import annotations

from slidethus.protocols import RenderBackend, RenderRequest, RenderResult


def render_with(backend: RenderBackend, request: RenderRequest) -> RenderResult:
    """Call a renderer through the stable backend protocol."""

    return backend.render(request)
