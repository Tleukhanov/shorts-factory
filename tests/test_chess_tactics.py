"""Tests for the tactics short planner and renderer."""

from __future__ import annotations

from pathlib import Path

import pytest

from shorts_clipper.chess import puzzle_db, tactics

FIXTURE = Path(__file__).with_suffix("").parent / "fixtures" / "puzzles.csv.zst"


@pytest.fixture
def sample_puzzle(tmp_path):
    cfg = puzzle_db.TacticsConfig(
        db_path=FIXTURE,
        cache_path=tmp_path / "selected.json",
        rating_min=1400,
        rating_max=2000,
        popularity_min=85,
        plays_min=2000,
        max_solution_moves=4,
        max_per_theme=1,
    )
    selected = puzzle_db.select_puzzles(FIXTURE, count=1, cfg=cfg)
    assert selected
    return selected[0]


def test_plan_tactic_has_four_frames(sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    assert len(plan.clip_plan.frames) == 4
    assert len(plan.clip_plan.holds) == 4
    assert plan.frame_starts[0] == 0.0


def test_question_frame_does_not_reveal_answer(sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    question = plan.clip_plan.frames[0]
    assert question.arrow is None
    assert not question.highlight_squares
    assert "найдёшь" in question.top_text.lower() or "тактик" in question.top_text.lower()


def test_reveal_frame_shows_solution(sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    reveal = plan.clip_plan.frames[1]
    assert reveal.arrow is not None
    assert reveal.highlight_squares
    assert reveal.accent == "good"
    assert reveal.bottom_text == tactics._move_san(sample_puzzle, sample_puzzle.solution_moves[0])


def test_voice_lines_are_short_and_safe(sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    assert plan.voice_lines[0] is not None
    assert "тактик" in plan.voice_lines[0].lower()
    assert plan.voice_lines[1] is not None
    # CTA voice is present.
    assert plan.voice_lines[3] is not None
    assert "Senpai" in plan.voice_lines[3]


def test_cta_frame_uses_full_screen_card(sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    cta = plan.clip_plan.frames[3]
    assert cta.cta == (plan.cta_top, plan.cta_bottom)


def test_render_tactic_without_voice_produces_video(tmp_path, sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    out = tmp_path / "tactic.mp4"
    result = tactics.render_tactic(plan, out, music_path=None, voice=False)
    assert result is not None
    assert result.is_file()
    assert result.stat().st_size > 1000
