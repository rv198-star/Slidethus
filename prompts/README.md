# Prompt Contracts

- `source-preserved/` contains prompts extracted from the supplied source and is immutable except for provenance metadata.
- `production/` contains Slidethus contracts. They define inputs, procedure, outputs and gates; they are not guaranteed to be optimal one-shot prompts for every model.
- Runtime adapters may translate a contract into provider-specific messages, but must preserve the artifact schema and source-integrity rules.
