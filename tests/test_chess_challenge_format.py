"""Tests for the club-challenge content format.

The format turns Lichess tournament games into viewer puzzles.  Engine-dependent
selection is mocked here so the tests run without Stockfish or network access.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
from pathlib import Path

import pytest

from shorts_clipper import __main__ as cli
from shorts_clipper.chess import challenge_format, challenges, lichess
from shorts_clipper.core.settings import Settings

HAVE_CHESS = bool(importlib.util.find_spec("chess"))

FIXTURE = Path(__file__).with_suffix("").parent / "fixtures" / "challenge.pgn"


@pytest.fixture
def sample_games():
    return lichess.parse_games(FIXTURE.read_text(encoding="utf-8"))


def _make_challenge(
    fen: str = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 1",
    move_number: int = 5,
    ply: int = 8,
    color: str = "white",
    best_uci: str = "e1g1",
    best_san: str = "O-O",
    gap_cp: int = 350,
    best_cp: int = 120,
    runner_up_san: str = "d2d4",
    header: dict | None = None,
) -> challenges.Challenge:
    return challenges.Challenge(
        fen=fen,
        move_number=move_number,
        ply=ply,
        color=color,
        best_uci=best_uci,
        best_san=best_san,
        gap_cp=gap_cp,
        best_cp=best_cp,
        runner_up_san=runner_up_san,
        header=header or {},
    )


def _mock_find_challenges(game, **kwargs):
    """Return one challenge per game, except the Visitor game which is empty."""
    headers = dict(getattr(game, "headers", {}) or {})
    if headers.get("White") == "Visitor":
        return []
    # Use the same position for the first and third games so dedup is exercised.
    return [
        _make_challenge(
            fen="r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 1",
            move_number=5,
            ply=8,
            color="white",
            best_uci="e1g1",
            best_san="O-O",
            gap_cp=350,
            best_cp=120,
            runner_up_san="d2d4",
            header=headers,
        )
    ]


def test_config_from_file(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(
        json.dumps(
            {
                "club_name": "TestClub",
                "lichess_team_url": "https://lichess.org/team/test",
                "whatsapp_url": "https://chat.whatsapp.com/test",
                "hashtags": ["#test"],
                "min_player_rating": 1600,
                "target_player_rating": 2100,
                "gap_cp_min": 350,
                "cta_top": "Join us",
                "cta_bottom": "Link below",
            }
        ),
        encoding="utf-8",
    )
    cfg = challenge_format.ChallengeConfig.from_file(path)
    assert cfg.club_name == "TestClub"
    assert cfg.min_player_rating == 1600
    assert cfg.target_player_rating == 2100
    assert cfg.gap_cp_min == 350
    assert cfg.hashtags == ("#test",)


def test_default_config_has_sensible_values():
    cfg = challenge_format.ChallengeConfig()
    assert cfg.club_name
    assert cfg.min_player_rating >= 1000
    assert cfg.gap_cp_min >= 100
    assert cfg.max_games > 0


@pytest.mark.skipif(not HAVE_CHESS, reason="python-chess not installed")
def test_find_challenges_in_games_skips_low_rated(sample_games, monkeypatch):
    monkeypatch.setattr("shorts_clipper.chess.challenges.find_challenges", _mock_find_challenges)
    cfg = challenge_format.ChallengeConfig(min_player_rating=1500, gap_cp_min=300)
    results = challenge_format.find_challenges_in_games(sample_games, cfg)
    assert results
    for _challenge, headers, _rating in results:
        white_elo = int(headers.get("WhiteElo") or 0)
        black_elo = int(headers.get("BlackElo") or 0)
        assert white_elo >= 1500 or black_elo >= 1500


@pytest.mark.skipif(not HAVE_CHESS, reason="python-chess not installed")
def test_find_challenges_prefers_club_members(sample_games, monkeypatch):
    monkeypatch.setattr("shorts_clipper.chess.challenges.find_challenges", _mock_find_challenges)
    cfg = challenge_format.ChallengeConfig(
        min_player_rating=1500, gap_cp_min=300, member_min_rating=1800
    )
    results = challenge_format.find_challenges_in_games(
        sample_games, cfg, club_members=["clubmember"]
    )
    assert results
    top_headers = results[0][1]
    white = str(top_headers.get("White", "")).lower()
    black = str(top_headers.get("Black", "")).lower()
    assert "clubmember" in (white, black)


@pytest.mark.skipif(not HAVE_CHESS, reason="python-chess not installed")
def test_find_challenges_deduplicates_by_position_and_move(sample_games, monkeypatch):
    monkeypatch.setattr("shorts_clipper.chess.challenges.find_challenges", _mock_find_challenges)
    cfg = challenge_format.ChallengeConfig(min_player_rating=1500, gap_cp_min=300)
    results = challenge_format.find_challenges_in_games(sample_games, cfg)
    keys = {f"{c.fen} {c.best_uci}" for c, _h, _r in results}
    assert len(keys) == len(results)


@pytest.mark.skipif(not HAVE_CHESS, reason="python-chess not installed")
def test_find_challenges_returns_mover_rating(sample_games, monkeypatch):
    monkeypatch.setattr("shorts_clipper.chess.challenges.find_challenges", _mock_find_challenges)
    cfg = challenge_format.ChallengeConfig(min_player_rating=1500, gap_cp_min=300)
    results = challenge_format.find_challenges_in_games(sample_games, cfg)
    # The first game is kept by dedup; the challenge side is white.
    assert results[0][2] == 2200


def test_plan_challenge_game_has_four_frames():
    challenge = _make_challenge()
    headers = {
        "White": "Test White",
        "Black": "Test Black",
        "WhiteElo": "2000",
    }
    cfg = challenge_format.ChallengeConfig()
    plan = challenge_format.plan_challenge_game(challenge, headers, cfg)
    assert len(plan.clip_plan.frames) == 4
    assert len(plan.clip_plan.holds) == 4
    assert plan.frame_starts[0] == 0.0


def test_plan_challenge_game_question_gives_nothing_away():
    challenge = _make_challenge()
    headers = {"White": "A", "Black": "B", "WhiteElo": "2000"}
    cfg = challenge_format.ChallengeConfig()
    plan = challenge_format.plan_challenge_game(challenge, headers, cfg)
    question = plan.clip_plan.frames[0]
    assert question.highlight_squares == ()
    assert question.arrow is None
    assert question.eval_text is None


def test_plan_challenge_game_answer_has_arrow_and_rating():
    challenge = _make_challenge()
    headers = {"White": "A", "Black": "B", "WhiteElo": "2000"}
    cfg = challenge_format.ChallengeConfig()
    plan = challenge_format.plan_challenge_game(challenge, headers, cfg)
    answer = plan.clip_plan.frames[2]
    assert answer.arrow is not None
    assert answer.accent == "good"
    assert "O-O" in answer.top_text
    assert "2000" in answer.bottom_text


def test_plan_challenge_game_voice_lines():
    challenge = _make_challenge()
    headers = {"White": "A", "Black": "B", "WhiteElo": "2050"}
    cfg = challenge_format.ChallengeConfig()
    plan = challenge_format.plan_challenge_game(challenge, headers, cfg)
    assert plan.voice_lines[0] is not None
    assert "2050" in plan.voice_lines[0]
    assert plan.voice_lines[1] is None
    assert plan.voice_lines[2] is not None
    assert "O-O" in plan.voice_lines[2]
    assert plan.voice_lines[3] is not None
    assert "клубу" in plan.voice_lines[3]


def test_plan_challenge_game_cta_is_full_screen_card():
    challenge = _make_challenge()
    headers = {}
    cfg = challenge_format.ChallengeConfig(cta_top="Top", cta_bottom="Bottom")
    plan = challenge_format.plan_challenge_game(challenge, headers, cfg)
    cta = plan.clip_plan.frames[3]
    assert cta.cta == ("Top", "Bottom")


def test_write_metadata_contains_title_and_links(tmp_path):
    challenge = _make_challenge(
        header={"White": "A", "Black": "B", "Site": "https://lichess.org/xyz"}
    )
    cfg = challenge_format.ChallengeConfig(
        club_name="TestClub",
        lichess_team_url="https://lichess.org/team/test",
        whatsapp_url="https://chat.whatsapp.com/test",
        hashtags=["#test"],
    )
    plan = challenge_format.plan_challenge_game(challenge, challenge.header, cfg)
    out = tmp_path / "clip.mp4"
    meta = challenge_format.write_metadata(plan, out, cfg)
    text = meta.read_text(encoding="utf-8")
    assert "Сможешь сыграть как" in text
    assert "TestClub" in text
    assert "https://lichess.org/team/test" in text
    assert "https://chat.whatsapp.com/test" in text
    assert "#test" in text


def test_tournament_id_from_args():
    assert challenge_format.tournament_id_from_args([]) == ""
    assert challenge_format.tournament_id_from_args(["MwiQDf4S"]) == "MwiQDf4S"
    assert (
        challenge_format.tournament_id_from_args(["https://lichess.org/tournament/MwiQDf4S"])
        == "MwiQDf4S"
    )


def test_parser_accepts_club_challenge_format():
    parser = cli.build_parser()
    args = parser.parse_args(
        ["chess", "https://lichess.org/tournament/MwiQDf4S", "--format", "club-challenge"]
    )
    assert args.format == "club-challenge"


@pytest.mark.skipif(not HAVE_CHESS, reason="python-chess not installed")
def test_render_challenge_without_voice_produces_video(tmp_path):
    challenge = _make_challenge()
    headers = {"White": "A", "Black": "B"}
    cfg = challenge_format.ChallengeConfig()
    plan = challenge_format.plan_challenge_game(challenge, headers, cfg)
    out = tmp_path / "challenge.mp4"
    result = challenge_format.render_challenge(plan, out, music_path=None, voice=False)
    assert result is not None
    assert result.is_file()
    assert result.stat().st_size > 1000


def test_club_challenge_command_smoke(sample_games, monkeypatch):
    """The CLI branch wires fetch, selection, render and metadata together."""
    from unittest import mock

    fake_challenge = _make_challenge()

    def _fake_find_challenges(_games, _cfg, club_members=None):
        return [(fake_challenge, fake_challenge.header, 2000)]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = argparse.Namespace(
            path=["https://lichess.org/tournament/abc"],
            output=str(root / "out"),
            count=1,
            min_ply=None,
            max_games=None,
            music=None,
            no_music=True,
            no_voice=True,
            continue_on_error=False,
            used_path=None,
            challenge_config=None,
        )
        # Point music/settings at the temp root so default bed resolution is safe.
        settings = Settings(
            music_dir=root / "music",
            chess_used_path=root / "used.json",
        )

        with (
            mock.patch(
                "shorts_clipper.chess.lichess.fetch_tournament",
                return_value={"fullName": "Test Arena"},
            ),
            mock.patch(
                "shorts_clipper.chess.lichess.fetch_tournament_games",
                return_value=sample_games,
            ),
            mock.patch(
                "shorts_clipper.chess.lichess.fetch_team_members",
                return_value=[],
            ),
            mock.patch(
                "shorts_clipper.chess.challenge_format.find_challenges_in_games",
                side_effect=_fake_find_challenges,
            ),
            mock.patch(
                "shorts_clipper.chess.challenge_format.render_challenge",
                side_effect=lambda plan, out, **kw: Path(out).write_bytes(b"") or Path(out),
            ),
            mock.patch("shorts_clipper.chess.challenge_format.write_metadata") as write_meta,
        ):
            code = cli._cmd_chess_club_challenge(args, settings)

        assert code == 0
        assert write_meta.call_count == 1
