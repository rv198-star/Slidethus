# Intake Contract

## Purpose

Transform a user request and available source inventory into a schema-valid `project_brief` without asking questions already answered by the inputs.

## Required inputs

- user request;
- known source list and metadata;
- host capability matrix;
- prior accepted decisions and assumptions, when present.

## Procedure

1. Extract purpose, audience, desired action, presentation context, page/time constraints, output formats, editability target, brand rules, language, citation policy and approval mode.
2. Distinguish explicit facts, safe inferences, assumptions and unresolved questions.
3. Ask only questions that materially change the narrative, evidence requirements, page count, delivery format or approval boundary.
4. Mark each open question as blocking or non-blocking.
5. Do not invent a brand system, deadline, audience authority or research permission.
6. Emit only data that conforms to `schemas/project_brief.schema.json`.

## Exit conditions

- purpose and desired outcome are concrete;
- at least one audience exists;
- page count range is coherent;
- output and editability targets are declared;
- no blocking question is silently treated as answered.
