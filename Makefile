.PHONY: install test lint validate demo audit verify clean

install:
	python -m pip install -e '.[dev]'

test:
	python -m pytest

lint:
	python -m compileall -q src tests scripts
	ruff check src tests scripts

validate:
	python scripts/validate_all.py

demo:
	python -m slidethus.cli render-wireframe examples/minimal_project

audit:
	python scripts/audit_package.py

verify: lint test validate audit

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	rm -rf build dist *.egg-info src/*.egg-info
