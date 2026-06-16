"""The package imports cleanly and exposes its public surface."""

from __future__ import annotations

import importlib

import gmat_copilot


def test_version_is_a_string() -> None:
    assert isinstance(gmat_copilot.__version__, str)
    assert gmat_copilot.__version__.count(".") >= 2


def test_public_surface() -> None:
    from gmat_copilot import CopilotResult, LintReport, Severity, draft

    assert callable(draft)
    assert CopilotResult.__name__ == "CopilotResult"
    assert LintReport.__name__ == "LintReport"
    assert Severity.ERROR.value == "error"


def test_all_is_exported() -> None:
    for name in gmat_copilot.__all__:
        assert hasattr(gmat_copilot, name), name


def test_subpackages_import() -> None:
    for module in (
        "gmat_copilot.providers",
        "gmat_copilot.rag",
        "gmat_copilot.eval",
        "gmat_copilot.generate",
        "gmat_copilot.validate",
        "gmat_copilot.cli",
    ):
        assert importlib.import_module(module) is not None
