from __future__ import annotations

from typer.testing import CliRunner

from learnit_study.cli import app


runner = CliRunner()


def test_cli_help_loads() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "learnit" in result.output.lower()


def test_placeholder_command_loads() -> None:
    result = runner.invoke(app, ["auth", "check"])

    assert result.exit_code == 0
    assert "not implemented yet" in result.output
