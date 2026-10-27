"""Tests for the real-game analysis format.

The format takes a decisive moment from a real game and turns it into a short
with hook, reveal, after and CTA frames plus Russian voiceover.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from shorts_clipper.chess import analysis, analysis_format, lichess

HAVE_CHESS = bool(importlib.util.find_spec("chess"))

FIXTURE = Path(__file__).with_suffix("").parent / "fixtures" / "tournament.pgn"


@pytest.fixture
def sample_games():
    return lichess.parse_games(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def sample_decision(sample_games):
    games = sample_games
    decisions = []
    for game in games:
        found = analysis.find_decisions(
            game, critical_cp=200, min_ply=10, limit=1, use_engine=False
        )
        if found:
            decisions.append(found[0])
    assert decisions
    return max(decisions, key=lambda d: d.mover_loss_cp)


def test_config_from_file(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(
        json.dumps(
            {
                "club_name": "TestClub",
                "lichess_team_url": "https://lichess.org/team/test",
                "whatsapp_url": "https://chat.whatsapp.com/test",
                "hashtags": ["#test"],
                "critical_cp": 250,
                "min_ply": 12,
                "cta_top": "Join us",
                "cta_bottom": "Link below",
            }
        ),
        encoding="utf-8",
    )
    cfg = analysis_format.AnalysisConfig.from_file(path)
    assert cfg.club_name == "TestClub"
    assert cfg.critical_cp == 250
    assert cfg.min_ply == 12
    assert cfg.hashtags == ("#test",)


def test_default_config_has_sensible_values():
    cfg = analysis_format.AnalysisConfig()
    assert cfg.club_name
    assert cfg.critical_cp >= 100
    assert cfg.min_ply >= 10


def test_plan_analysis_has_four_frames(sample_decision):
    cfg = analysis_format.AnalysisConfig()
    plan = analysis_format.plan_analysis(sample_decision, cfg)
    assert len(plan.clip_plan.frames) == 4
    assert len(plan.clip_plan.holds) == 4
    assert plan.frame_starts[0] == 0.0


def test_plan_analysis_reveal_has_arrow(sample_decision):
    cfg = analysis_format.AnalysisConfig()
    plan = analysis_format.plan_analysis(sample_decision, cfg)
    reveal = plan.clip_plan.frames[1]
    assert reveal.arrow is not None
    assert reveal.accent == "bad"
    assert sample_decision.san in reveal.top_text


def test_plan_analysis_cta_is_full_screen_card(sample_decision):
    cfg = analysis_format.AnalysisConfig(cta_top="Top", cta_bottom="Bottom")
    plan = analysis_format.plan_analysis(sample_decision, cfg)
    cta = plan.clip_plan.frames[3]
    assert cta.cta == ("Top", "Bottom")


def test_voice_lines_cover_hook_reveal_and_cta(sample_decision):
    cfg = analysis_format.AnalysisConfig(club_name="TestClub")
    plan = analysis_format.plan_analysis(sample_decision, cfg)
    assert plan.voice_lines[0] is not None
    assert "ошибк" in plan.voice_lines[0].lower()
    assert plan.voice_lines[1] is not None
    assert sample_decision.san in plan.voice_lines[1]
    assert plan.voice_lines[2] is None
    assert plan.voice_lines[3] is not None
    assert "TestClub" in plan.voice_lines[3]


def test_write_metadata_contains_title_and_links(tmp_path, sample_decision):
    cfg = analysis_format.AnalysisConfig(
        club_name="TestClub",
        lichess_team_url="https://lichess.org/team/test",
        whatsapp_url="https://chat.whatsapp.com/test",
        hashtags=["#test"],
    )
    plan = analysis_format.plan_analysis(sample_decision, cfg)
    out = tmp_path / "clip.mp4"
    meta = analysis_format.write_metadata(plan, out, cfg)
    text = meta.read_text(encoding="utf-8")
    assert "Разбор партии" in text
    assert sample_decision.san in text
    assert "https://lichess.org/team/test" in text
    assert "https://chat.whatsapp.com/test" in text
    assert "#test" in text


def test_select_moments_picks_best_across_games(sample_games):
    cfg = analysis_format.AnalysisConfig(critical_cp=200, min_ply=10)
    decisions, stats = analysis_format.select_moments(
        sample_games, count=5, cfg=cfg
    )
    assert decisions
    assert len(decisions) <= 2  # fixture has two games with blunders
    losses = [d.mover_loss_cp for d in decisions]
    assert losses == sorted(losses, reverse=True)
    assert stats["scanned"] == 3
    assert stats["too_short"] == 1


def test_select_moments_prefers_club_members(sample_games):
    cfg = analysis_format.AnalysisConfig(critical_cp=200, min_ply=10)
    decisions, stats = analysis_format.select_moments(
        sample_games, count=5, cfg=cfg, club_members=["clubmember"]
    )
    assert decisions
    for decision in decisions:
        header = dict(decision.header or {})
        white = str(header.get("White", "")).lower()
        black = str(header.get("Black", "")).lower()
        assert "clubmember" in (white, black)
    assert stats["not_member"] >= 1


def test_select_moments_deduplicates_by_position_and_move(sample_games):
    cfg = analysis_format.AnalysisConfig(critical_cp=200, min_ply=10)
    decisions, _ = analysis_format.select_moments(
        sample_games, count=5, cfg=cfg
    )
    keys = {f"{d.fen_before} {d.uci}" for d in decisions}
    assert len(keys) == len(decisions)


@pytest.mark.skipif(not HAVE_CHESS, reason="python-chess not installed")
def test_render_analysis_without_voice_produces_video(tmp_path, sample_decision):
    plan = analysis_format.plan_analysis(sample_decision)
    out = tmp_path / "analysis.mp4"
    result = analysis_format.render_analysis(plan, out, music_path=None, voice=False)
    assert result is not None
    assert result.is_file()
    assert result.stat().st_size > 1000
