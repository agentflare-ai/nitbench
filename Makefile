.PHONY: all setup test lint

all: setup test

setup:
	uv sync

test:
	uv run pytest tests/
