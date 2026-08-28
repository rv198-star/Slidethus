.PHONY: install test lint validate m2-exit m3-exit m4-exit renderer-test demo audit verify clean

install:
	python -m pip install -e '.[dev]'

test:
	python -m pytest

lint:
	python -m compileall -q src tests scripts
	ruff check src tests scripts

validate:
	python scripts/validate_all.py

m2-exit:
	python scripts/validate_m2_exit.py

m3-exit:
	python scripts/validate_m3_exit.py

m4-exit:
	python scripts/validate_m4_exit.py

renderer-test:
	npm test --prefix renderers/pptxgenjs

demo:
	python -m slidethus.cli render-wireframe examples/minimal_project

audit:
	python scripts/audit_package.py

verify: lint test validate m2-exit m3-exit m4-exit renderer-test audit

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	rm -rf build dist *.egg-info src/*.egg-info
