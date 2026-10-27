"""Tests for Lichess tournament/team ingestion.

All network calls are mocked; the fixtures under ``tests/fixtures/`` provide
real-enough PGNs and NDJSON so parsing paths are exercised.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from shorts_clipper.chess import lichess

FIXTURE = Path(__file__).with_suffix("").parent / "fixtures" / "tournament.pgn"


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "lichess"


@pytest.fixture
def pgn_text():
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_tournament_id_from_url():
    assert lichess._parse_tournament_id(
        "https://lichess.org/tournament/MwiQDf4S"
    ) == "MwiQDf4S"


def test_parse_tournament_id_from_bare_id():
    assert lichess._parse_tournament_id("MwiQDf4S") == "MwiQDf4S"


def test_parse_tournament_id_empty():
    assert lichess._parse_tournament_id("") == ""


def test_fetch_tournament_uses_cache_and_parses_json(cache):
    payload = {"id": "abc", "fullName": "Test Arena"}
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "abc.json").write_text(json.dumps(payload), encoding="utf-8")

    with mock.patch("requests.get") as get:
        result = lichess.fetch_tournament("abc", cache_dir=cache)
        get.assert_not_called()
    assert result["fullName"] == "Test Arena"


def test_fetch_tournament_fetches_when_cache_missing(cache):
    payload = {"id": "xyz", "name": "Club Arena"}
    resp = mock.Mock()
    resp.text = json.dumps(payload)
    resp.raise_for_status = mock.Mock()

    with mock.patch("requests.get", return_value=resp) as get:
        result = lichess.fetch_tournament("xyz", cache_dir=cache)
        get.assert_called_once()
    assert result["name"] == "Club Arena"
    assert (cache / "xyz.json").is_file()


def test_fetch_tournament_games_parses_fixture(cache, pgn_text):
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "test_games.pgn").write_text(pgn_text, encoding="utf-8")

    games = lichess.fetch_tournament_games("test", cache_dir=cache)
    assert len(games) == 3
    assert games[0].headers["White"] == "ClubMember"


def test_fetch_tournament_games_fetches_and_caches(cache, pgn_text):
    resp = mock.Mock()
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    resp.content = pgn_text.encode("utf-8")
    resp.raise_for_status = mock.Mock()

    with mock.patch("requests.get", return_value=resp) as get:
        games = lichess.fetch_tournament_games("live", cache_dir=cache)
        get.assert_called_once()
    assert len(games) == 3
    assert (cache / "live_games.pgn").is_file()


def test_fetch_team_members_parses_ndjson(cache):
    cache.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"name": "Alice", "username": "alice123"}),
        json.dumps({"name": "Bob"}),
        "",
    ]
    (cache / "senpai_members.json").write_text("\n".join(lines), encoding="utf-8")

    members = lichess.fetch_team_members("senpai", cache_dir=cache)
    assert set(members) == {"alice123", "bob"}


def test_fetch_team_members_fetches_and_caches(cache):
    lines = [
        json.dumps({"name": "Carol"}),
        json.dumps({"username": "dave"}),
    ]
    resp = mock.Mock()
    resp.text = "\n".join(lines)
    resp.content = resp.text.encode("utf-8")
    resp.raise_for_status = mock.Mock()

    with mock.patch("requests.get", return_value=resp) as get:
        members = lichess.fetch_team_members("senpai", cache_dir=cache)
        get.assert_called_once()
    assert set(members) == {"carol", "dave"}
    assert (cache / "senpai_members.json").is_file()


def test_concurrency_limit_is_respected(cache):
    """The global semaphore plus a small sleep keeps Lichess requests polite."""
    resp = mock.Mock()
    resp.text = json.dumps({"id": "a"})
    resp.raise_for_status = mock.Mock()

    with mock.patch("requests.get", return_value=resp):
        with mock.patch("time.sleep") as sleep:
            lichess.fetch_tournament("a", cache_dir=cache)
            sleep.assert_called_once()
