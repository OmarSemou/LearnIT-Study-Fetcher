from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from learnit_study import auth
from learnit_study.cli import app


runner = CliRunner()


def test_cli_help_loads() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "learnit" in result.output.lower()


def test_auth_check_command_loads(monkeypatch) -> None:
    monkeypatch.setattr(
        auth,
        "check",
        lambda cookie=None: "LearnIT authentication succeeded. Cookie accepted and Moodle sesskey found.",
    )

    result = runner.invoke(app, ["auth", "check"])

    assert result.exit_code == 0
    assert "authentication succeeded" in result.output


def test_auth_check_cookie_option_takes_priority(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, str | None] = {}
    monkeypatch.setenv("LEARNIT_COOKIE", "env-cookie")
    monkeypatch.chdir(tmp_path)
    Path("cookie.txt").write_text("file-cookie", encoding="utf-8")

    def fake_check(cookie=None):
        seen["cookie"] = cookie
        return "ok"

    monkeypatch.setattr(auth, "check", fake_check)

    result = runner.invoke(app, ["auth", "check", "--cookie", "cli-cookie"])

    assert result.exit_code == 0
    assert seen["cookie"] == "cli-cookie"
