# Slide Planner Contract

## Purpose

Create `deck_outline` and `slide_specs` as two distinct layers: the first controls pacing and sequence; the second defines the semantic content of each page.

## Deck Outline rules

- assign stable `S-###` IDs before visual design;
- one primary takeaway per active slide;
- write assertion-style headlines where appropriate;
- bind factual slides to evidence IDs;
- use slide roles deliberately;
- remove, merge or split slides before layout;
- maintain contiguous ordinals only for active slides.

## Slide Specs rules

For each active slide define:

- the audience question;
- the core message;
- content blocks with stable `BLK-S###-##` IDs;
- semantic role, content type, priority and evidence IDs;
- visual relationship, acceptable layout families and patterns to avoid;
- density budget and editability intent.

Do not add decorative blocks before the semantic structure is complete. Do not push unsupported factual detail into speaker notes to bypass evidence policy.
