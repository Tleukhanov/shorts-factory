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


def test_plan_tactic_covers_the_whole_solution(sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    # Question + (6 animation frames + landing frame) per move + final + CTA.
    expected = 1 + 7 * len(sample_puzzle.solution_moves) + 2
    assert len(plan.clip_plan.frames) == expected
    assert len(plan.clip_plan.holds) == expected
    assert plan.frame_starts[0] == 0.0


def test_question_frame_does_not_reveal_answer(sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    question = plan.clip_plan.frames[0]
    assert question.arrow is None
    assert not question.highlight_squares
    assert "найдёшь" in question.top_text.lower() or "тактик" in question.top_text.lower()


def test_solution_animates_the_piece(sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    moving = [frame for frame in plan.clip_plan.frames if frame.moving is not None]
    assert moving, "the move should have slide frames"
    assert any(0.0 < frame.moving[3] < 1.0 for frame in moving)
    assert all(frame.hidden_squares for frame in moving)


def test_reveal_frame_shows_solution(sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    reveal = next(frame for frame in plan.clip_plan.frames if frame.arrow is not None)
    assert reveal.highlight_squares
    assert reveal.accent == "good"
    assert reveal.bottom_text == tactics._move_san(sample_puzzle, sample_puzzle.solution_moves[0])


def test_voice_lines_are_short_and_safe(sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    assert plan.voice_lines[0] is not None
    assert "тактик" in plan.voice_lines[0].lower()
    assert any(plan.voice_lines[1:])
    # CTA voice is present on the last frame.
    assert plan.voice_lines[-1] is not None
    assert "Senpai" in plan.voice_lines[-1]


def test_cta_frame_uses_full_screen_card(sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    cta = plan.clip_plan.frames[-1]
    assert cta.cta == (plan.cta_top, plan.cta_bottom)


def test_final_frame_reaches_the_mate(sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    final = plan.clip_plan.frames[-2]
    assert final.top_text in {"Мат!", "Позиция выиграна"}
    if final.top_text == "Мат!":
        import chess

        assert chess.Board(final.fen).is_checkmate()


def test_render_tactic_without_voice_produces_video(tmp_path, sample_puzzle):
    plan = tactics.plan_tactic(sample_puzzle)
    out = tmp_path / "tactic.mp4"
    result = tactics.render_tactic(plan, out, music_path=None, voice=False)
    assert result is not None
    assert result.is_file()
    assert result.stat().st_size > 1000
