"""Chess content: game analysis and board rendering."""

from __future__ import annotations

from shorts_clipper.chess.analysis import (
    Decision,
    available,
    find_decisions,
    has_engine,
    load_pgn,
    load_pgn_file,
    material_eval,
)
from shorts_clipper.chess.analysis_format import (
    AnalysisConfig,
    AnalysisRenderPlan,
    plan_analysis,
    render_analysis,
    select_moments,
)
from shorts_clipper.chess.board import FrameSpec, render_frame
from shorts_clipper.chess.drama import (
    DramaConfig,
    DramaRenderPlan,
    WrongMove,
    find_wrong_moves,
    plan_drama,
    render_drama,
)
from shorts_clipper.chess.lichess import (
    fetch_team_members,
    fetch_tournament,
    fetch_tournament_games,
)
from shorts_clipper.chess.puzzle_db import Puzzle, TacticsConfig, download_db, select_puzzles
from shorts_clipper.chess.tactics import plan_tactic, render_tactic

__all__ = [
    "AnalysisConfig",
    "AnalysisRenderPlan",
    "Decision",
    "DramaConfig",
    "DramaRenderPlan",
    "FrameSpec",
    "Puzzle",
    "TacticsConfig",
    "WrongMove",
    "available",
    "download_db",
    "fetch_team_members",
    "fetch_tournament",
    "fetch_tournament_games",
    "find_decisions",
    "find_wrong_moves",
    "has_engine",
    "load_pgn",
    "load_pgn_file",
    "material_eval",
    "plan_analysis",
    "plan_drama",
    "plan_tactic",
    "render_analysis",
    "render_drama",
    "render_frame",
    "render_tactic",
    "select_moments",
    "select_puzzles",
]
