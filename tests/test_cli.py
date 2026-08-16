from __future__ import annotations

import pytest

from redscrape import cli
from redscrape.arctic import CoverageResult
from redscrape.engine import ArchiveResult


def test_parse_subreddits_removes_only_an_explicit_prefix() -> None:
    assert cli._parse_subs("rust,rstats,r/python,/r/golang") == [
        "rust",
        "rstats",
        "python",
        "golang",
    ]


def test_archive_requires_after_and_before() -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as missing_after:
        parser.parse_args(["archive", "python", "--before", "2026-08-17"])
    with pytest.raises(SystemExit) as missing_before:
        parser.parse_args(["archive", "python", "--after", "2026-08-16"])

    assert missing_after.value.code == 2
    assert missing_before.value.code == 2


def test_archive_help_exposes_exact_window_options_only(capsys) -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as stopped:
        parser.parse_args(["archive", "--help"])

    help_text = capsys.readouterr().out
    assert stopped.value.code == 0
    assert "--after" in help_text
    assert "--before" in help_text
    assert "--timezone" in help_text
    assert "--listing" not in help_text
    assert "--time " not in help_text
    assert "--limit" not in help_text


def test_archive_command_converts_timezone_and_returns_partial_exit_code(
    tmp_path, monkeypatch
) -> None:
    captured = {}

    class FakeArctic:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

    async def fake_archive(
        _arctic,
        reddit,
        _store,
        subs,
        window,
        *,
        with_comments,
        comment_sort,
        concurrency,
    ):
        captured.update(
            reddit=reddit,
            subs=subs,
            window=window,
            with_comments=with_comments,
            comment_sort=comment_sort,
            concurrency=concurrency,
        )
        failed = CoverageResult("python", complete=False, error="failed")
        return ArchiveResult(results={"python": failed}, comment_count=0)

    monkeypatch.setattr(cli, "ArcticShiftClient", FakeArctic)
    monkeypatch.setattr(cli, "archive", fake_archive)

    status = cli.main(
        [
            "archive",
            "python",
            "--after",
            "2026-05-16",
            "--before",
            "2026-05-17",
            "--timezone",
            "Asia/Kolkata",
            "--db",
            str(tmp_path / "archive.sqlite"),
        ]
    )

    assert status == 1
    assert captured["reddit"] is None
    assert captured["window"].after == 1778869800
    assert captured["window"].before == 1778956200
