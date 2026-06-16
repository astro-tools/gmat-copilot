"""Shared test fixtures and paths."""

from __future__ import annotations

from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"


@pytest.fixture
def valid_script() -> str:
    """A GMAT script that lints clean (no errors or warnings)."""
    return (DATA / "valid.script").read_text(encoding="utf-8")


@pytest.fixture
def invalid_script() -> str:
    """A script that fails to parse — a hard lint ERROR."""
    return (DATA / "invalid.script").read_text(encoding="utf-8")


@pytest.fixture
def eval_bundle() -> Path:
    """The committed deterministic recorded-eval bundle directory."""
    return DATA / "eval_smoke"
