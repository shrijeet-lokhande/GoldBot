.PHONY: all install dev db test lint format type-check check clean help

# Locate uv even when the package manager was installed to ~/.local/bin.
UV := $(shell command -v uv 2>/dev/null || echo "$(HOME)/.local/bin/uv")

all: install

install:
	$(UV) sync --frozen

dev:
	$(UV) sync --extra dev

db:
	$(UV) sync --extra dev --extra db

test:
	$(UV) run pytest

lint:
	$(UV) run ruff check .

format:
	$(UV) run ruff format .

type-check:
	$(UV) run mypy .

# Full quality gate used before any release or hand-over.
check: lint type-check test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache __pycache__ build dist *.egg-info

help:
	@echo "GoldBot development targets:"
	@echo "  make install   - sync locked dependencies (uv sync --frozen)"
	@echo "  make dev       - add dev extras (pytest, ruff, mypy, httpx)"
	@echo "  make db        - add database extras (SQLAlchemy/Alembic/psycopg)"
	@echo "  make test      - run the pytest suite"
	@echo "  make lint      - ruff checks"
	@echo "  make format    - ruff code formatting"
	@echo "  make type-check- mypy static type checking"
	@echo "  make check     - lint + type-check + tests (full gate)"
	@echo "  make clean     - remove caches and build artifacts"
