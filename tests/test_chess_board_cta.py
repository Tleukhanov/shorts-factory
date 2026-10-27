"""Tests for the full-screen CTA card in board rendering."""

from __future__ import annotations

from shorts_clipper.chess.board import FrameSpec, render_frame


def test_render_cta_produces_png(tmp_path):
    spec = FrameSpec(
        fen="8/8/8/8/8/8/8/8 w - - 0 1",
        top_text="",
        bottom_text="",
        cta=("Вступай в клуб", "Ссылка в описании"),
    )
    out = tmp_path / "cta.png"
    render_frame(spec, out)
    assert out.is_file()
    assert out.stat().st_size > 0


def test_render_board_still_works_without_cta(tmp_path):
    spec = FrameSpec(
        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        top_text="Найдёшь тактику?",
        bottom_text="Ход белых",
    )
    out = tmp_path / "board.png"
    render_frame(spec, out)
    assert out.is_file()
    assert out.stat().st_size > 0
