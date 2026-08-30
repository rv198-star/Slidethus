# ADR-0027｜Office Visual Quality as a Release Gate

Status: Accepted
Date: 2026-08-30

## Context

The first v1.0 decision treated successful SVG/PPTX generation, backend measurements, and a retrospective review with no promoted Major candidate as sufficient release evidence. A later human inspection of the actual Office previews disproved that assumption: list content escaped approved regions, evidence qualifications collided with body text, and nominally different layout families repeatedly collapsed to the same headline-plus-card-grid composition.

The failure was systemic. Text capacity used point values as logical canvas pixels even though Office renders one point as 4/3 logical pixels on the 96-dpi planning canvas. The visual-system artifact standardized palette and type tokens but did not provide executable page-role and component grammar. The release gate therefore certified artifact existence and structural validity, not the quality of the real deliverable.

## Decision

1. A PPTX release requires inspection of the real Office-rendered pages. SVG, Renderer IR, object counts, successful reopening, and editability measurements remain necessary evidence but cannot replace Office visual approval.
2. Font point sizes are converted to logical canvas units with a 4/3 scale in shared capacity calculations. SVG and PPTX paths must use the same physical-size assumption.
3. A layout family is implemented only when it creates an observable difference in primary geometry, reading path, hierarchy, and focal treatment. A different family label or connector decoration is insufficient.
4. The deterministic visual system includes executable page-role treatments, component variants, relationship marks, and deck-rhythm rules in addition to palette and typography tokens.
5. High-cardinality lists may remain one semantic Block, but renderers must expose their list items as editable visual units and must prove that every item remains within the approved region.
6. Visible overflow, collision, orphaned headline fragments, monotonous composition requiring deck-wide re-layout, or unreadable hierarchy is a Major issue and blocks release.
7. A previously recorded PASS is revoked when later target-renderer evidence shows a Critical or Major defect. Historical evidence is retained but is not the current release state.

## Consequences

- M6.6 is reopened and v1.0 remains `DO NOT RELEASE` until the new Office-reviewed deck is accepted.
- P5B owns relationship-driven geometry, P6 owns executable art direction, and P7 owns backend-specific text/layout parity.
- Regression fixtures cover layout-family differentiation, physical point scaling, structured high-cardinality lists, and connector geometry.
- Human visual review remains required because deterministic checks can prove containment and consistency but cannot fully certify taste.

## Non-goals

- No topic-, slide-, or exact-string-specific layout patches.
- No requirement to add decorative imagery to every page.
- No claim that one visual theme is universally appropriate.
