.PHONY: setup build test test-rust test-python lint clean

# Development setup: create venv, install deps, build native module
setup:
	uv venv .venv
	. .venv/bin/activate && uv pip install maturin pytest
	. .venv/bin/activate && maturin develop

# Rebuild the native module after Rust changes
build:
	. .venv/bin/activate && maturin develop

# Run all tests
test: test-rust test-python

# Rust tests (no venv needed)
test-rust:
	cargo test
	cargo clippy --all-targets

# Python tests (requires build first)
test-python:
	. .venv/bin/activate && pytest -v

# Lint
lint:
	cargo clippy --all-targets
	cargo fmt --check

# Clean
clean:
	cargo clean
	rm -rf .venv
