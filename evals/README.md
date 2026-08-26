# Evaluations

Eval cases describe inputs, expected artifacts, failure injections and Gate behavior. They are provider-neutral: a runtime may use different models or tools, but must preserve the same contracts.

Run deterministic foundation checks with `python scripts/validate_all.py`. Future model-backed evaluations should record model/provider/version, tool availability, seeds where applicable, cost and artifacts.
