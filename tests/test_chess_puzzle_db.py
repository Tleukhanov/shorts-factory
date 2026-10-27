"""Tests for the Lichess puzzle DB loader and quality filter."""

from __future__ import annotations

from pathlib import Path

from shorts_clipper.chess import puzzle_db

FIXTURE = Path(__file__).with_suffix("").parent / "fixtures" / "puzzles.csv.zst"


def test_parse_puzzle_reads_fixture():
    puzzles = list(puzzle_db.iter_puzzles(FIXTURE))
    assert len(puzzles) == 8
    ids = {p.id for p in puzzles}
    assert "t010" in ids


def test_puzzle_fen_applies_setup_move():
    puzzles = {p.id: p for p in puzzle_db.iter_puzzles(FIXTURE)}
    p = puzzles["t010"]
    fen = p.puzzle_fen()
    assert fen is not None
    # After 1...Kc4 the side to move is white.
    assert p.solver_color() == "white"


def test_quality_filter_rejects_boring_and_low_quality():
    cfg = puzzle_db.TacticsConfig(
        rating_min=1400,
        rating_max=2000,
        popularity_min=85,
        plays_min=2000,
        max_solution_moves=4,
    )
    puzzles = list(puzzle_db.iter_puzzles(FIXTURE))
    passed = [p for p in puzzles if puzzle_db._passes_quality(p, cfg)]
    passed_ids = {p.id for p in passed}
    # t010 fork, t011 sacrifice mateIn2, t012 quietMove pass.
    assert "t010" in passed_ids
    assert "t011" in passed_ids
    assert "t012" in passed_ids
    # t013 rating too low, t014 popularity too low, t016 hangingPiece, t017 mateIn1.
    assert "t013" not in passed_ids
    assert "t014" not in passed_ids
    assert "t016" not in passed_ids
    assert "t017" not in passed_ids
    # t015 has advantage but also fork, so it passes.
    assert "t015" in passed_ids


def test_select_puzzles_returns_diverse_top_quality(tmp_path):
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
    selected = puzzle_db.select_puzzles(FIXTURE, count=3, cfg=cfg)
    assert len(selected) == 3
    # All selected puzzles must be from the passing set.
    allowed = {"t010", "t011", "t012", "t015"}
    assert {p.id for p in selected} <= allowed
    # No duplicate primary themes because max_per_theme=1.
    themes = [p.primary_theme() for p in selected]
    assert len(themes) == len(set(themes))


def test_puzzle_theme_label_is_russian():
    puzzles = {p.id: p for p in puzzle_db.iter_puzzles(FIXTURE)}
    assert puzzles["t010"].theme_label() == "вилка"
    assert puzzles["t011"].theme_label() == "жертва"
    assert puzzles["t012"].theme_label() == "тихий ход"


def test_config_from_file_reads_json():
    path = Path("config/chess_tactics.json")
    cfg = puzzle_db.TacticsConfig.from_file(path)
    assert cfg.rating_min == 1400
    assert "fork" in cfg.allow_themes
    assert "mateIn1" in cfg.reject_themes
