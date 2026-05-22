#!/usr/bin/env sh
set -eu

python -m pip install -e ".[dev]"
python -m ruff format --check .
python -m ruff check .
python -m compileall src
python -m unittest discover -s tests
python -m polymarket_tracker.cli --config config.example.yaml init-db
python -m polymarket_tracker.cli --config config.example.yaml dry-run
python -m polymarket_tracker.cli --config config.example.yaml replay
python -m polymarket_tracker.cli --config config.example.yaml health

