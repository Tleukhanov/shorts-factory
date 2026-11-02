"""Tests for the viral puzzle-drama format.

The format is a frame plan plus a music-only render: hook, wrong moves, answer,
full solution, mate and CTA.  These tests pin that structure, the grayscale
board, the coloured arrows, metadata, and a real render without TTS.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from shorts_clipper.chess import beats, board, drama, puzzle_db
from shorts_clipper.chess.engine import Eval

FIXTURE = Path(__file__).with_suffix("").parent / "fixtures" / "puzzles.csv.zst"
CONFIG = Path(__file__).resolve().parents[1] / "config" / "chess_drama.json"


@pytest.fixture(scope="module")
def sample_puzzle(tmp_path_factory):
    cfg = puzzle_db.TacticsConfig(
        db_path=FIXTURE,
        cache_path=tmp_path_factory.mktemp("drama") / "selected.json",
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


@pytest.fixture
def drama_cfg():
    return drama.DramaConfig.from_file(CONFIG)


def _wrong_moves(puzzle, count=2):
    import chess

    board_ = chess.Board(puzzle.puzzle_fen())
    answer = chess.Move.from_uci(puzzle.solution_moves[0])
    out = []
    for move in board_.legal_moves:
        if move == answer:
            continue
        out.append(drama.WrongMove(move.uci(), board_.san(move), -50 * len(out)))
        if len(out) >= count:
            break
    assert len(out) == count
    return out


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


def test_config_loads_the_repo_file(drama_cfg):
    assert drama_cfg.club_name
    assert drama_cfg.hook_label_mate == "НАЙДИ МАТ"
    assert drama_cfg.hook_label_endgame == "ВЫИГРАЙ ЭНДШПИЛЬ"
    assert drama_cfg.hook_label_tactic == "НАЙДИ ЛУЧШИЙ ХОД"
    assert drama_cfg.answer_label == "ВОТ ОТВЕТ"
    assert drama_cfg.board_style == "mono"
    assert drama_cfg.beat_sync is True
    assert drama_cfg.max_wrong_moves >= 1
    assert isinstance(drama_cfg.hashtags, tuple)
    assert isinstance(drama_cfg.wrong_labels, list)


def test_missing_config_falls_back_to_defaults(tmp_path):
    cfg = drama.DramaConfig.from_file(tmp_path / "absent.json")
    assert cfg.hook_label_mate == "НАЙДИ МАТ"
    assert cfg.hook_label_endgame == "ВЫИГРАЙ ЭНДШПИЛЬ"
    assert cfg.hook_label_tactic == "НАЙДИ ЛУЧШИЙ ХОД"
    assert cfg.board_style == "mono"
    assert cfg.music_path.endswith(".wav")


def _with_themes(puzzle: puzzle_db.Puzzle, *themes: str) -> puzzle_db.Puzzle:
    return dataclasses.replace(puzzle, themes=frozenset(themes))


def test_hook_label_matches_the_puzzle_type(sample_puzzle, drama_cfg):
    for themes in (("mate",), ("mateIn2",), ("mateIn3", "sacrifice")):
        assert (
            drama._hook_label(_with_themes(sample_puzzle, *themes), drama_cfg)
            == drama_cfg.hook_label_mate
        )
    for themes in (("endgame",), ("pawnEndgame",), ("zugzwang",), ("opposition",)):
        assert (
            drama._hook_label(_with_themes(sample_puzzle, *themes), drama_cfg)
            == drama_cfg.hook_label_endgame
        )
    for themes in (("fork",), ("pin", "hangingPiece"), ("quietMove",)):
        assert (
            drama._hook_label(_with_themes(sample_puzzle, *themes), drama_cfg)
            == drama_cfg.hook_label_tactic
        )


def test_legacy_hook_label_still_overrides_the_theme(sample_puzzle):
    cfg = drama.DramaConfig(hook_label="СТАРЫЙ ЗАГОЛОВОК")
    assert drama._hook_label(_with_themes(sample_puzzle, "mateIn2"), cfg) == (
        "СТАРЫЙ ЗАГОЛОВОК"
    )


def test_music_resolution_prefers_config_then_first_track(tmp_path):
    cfg = drama.DramaConfig(music_path=str(tmp_path / "missing.wav"))
    (tmp_path / "b.wav").write_bytes(b"x")
    (tmp_path / "a.mp3").write_bytes(b"x")

    assert drama.resolve_music(cfg, music_dir=tmp_path, allow_generate=False).name == "a.mp3"

    explicit = tmp_path / "real.wav"
    explicit.write_bytes(b"x")
    assert (
        drama.resolve_music(
            cfg, explicit=explicit, music_dir=tmp_path, allow_generate=False
        )
        == explicit
    )


# --------------------------------------------------------------------------
# Wrong-move selection
# --------------------------------------------------------------------------


def test_find_wrong_moves_drops_the_best_move(sample_puzzle, monkeypatch):
    import chess

    board_ = chess.Board(sample_puzzle.puzzle_fen())
    legal = list(board_.legal_moves)
    best, second, third = legal[0], legal[1], legal[2]

    def fake_top_moves(fen, count=2, depth_override=None):
        return [
            (best.uci(), Eval(cp=500)),
            (second.uci(), Eval(cp=120)),
            (third.uci(), Eval(cp=-40)),
        ]

    monkeypatch.setattr(drama.engine, "top_moves", fake_top_moves)
    got = drama.find_wrong_moves(sample_puzzle, count=2)
    assert [wrong.uci for wrong in got] == [second.uci(), third.uci()]
    assert [wrong.eval_cp for wrong in got] == [120, -40]
    assert all(wrong.san for wrong in got)


def test_find_wrong_moves_without_an_engine_is_empty(sample_puzzle, monkeypatch):
    monkeypatch.setattr(drama.engine, "top_moves", lambda *args, **kwargs: None)
    assert drama.find_wrong_moves(sample_puzzle) == []


def test_the_curated_answer_is_never_labelled_wrong(sample_puzzle, monkeypatch):
    """A red arrow on the real solution would make the clip contradict itself."""
    import chess

    board_ = chess.Board(sample_puzzle.puzzle_fen())
    answer = sample_puzzle.solution_moves[0]
    other = next(
        move for move in board_.legal_moves if move.uci() != answer
    )

    def fake_top_moves(fen, count=2, depth_override=None):
        return [
            (other.uci(), Eval(cp=400)),
            (answer, Eval(cp=100)),
        ]

    monkeypatch.setattr(drama.engine, "top_moves", fake_top_moves)
    assert drama.find_wrong_moves(sample_puzzle, count=2) == []


# --------------------------------------------------------------------------
# Plan structure
# --------------------------------------------------------------------------


def test_plan_has_hook_wrong_answer_mate_and_cta(sample_puzzle, drama_cfg):
    import chess

    wrongs = _wrong_moves(sample_puzzle)
    plan = drama.plan_drama(sample_puzzle, wrongs, drama_cfg)
    frames = plan.clip_plan.frames

    hook = frames[0]
    assert hook.headline == drama._hook_label(sample_puzzle, drama_cfg)
    assert hook.arrow is None
    assert not hook.highlight_squares
    assert hook.board_style == "mono"
    assert hook.fen == sample_puzzle.puzzle_fen()

    wrong_frames = [frame for frame in frames if frame.accent == "bad"]
    assert len(wrong_frames) == len(wrongs)
    for frame in wrong_frames:
        assert frame.headline in drama_cfg.wrong_labels
        assert frame.arrow is not None
        assert frame.highlight_squares
        assert frame.arrow_color == "bad"
        assert frame.bottom_text

    answer = next(frame for frame in frames if frame.headline == drama_cfg.answer_label)
    assert answer.accent == "good"
    assert answer.arrow_color == "good"
    assert answer.arrow is not None
    assert answer.highlight_squares
    assert answer.fen == sample_puzzle.puzzle_fen()
    assert answer.bottom_text == plan.solution_sans[0]

    mate = next(frame for frame in frames if frame.headline == "МАТ!")
    assert mate.accent == "good"
    assert chess.Board(mate.fen).is_checkmate()

    line_landings = [
        frame
        for frame in frames
        if frame.headline is None and frame.arrow is not None and frame.accent == "good"
    ]
    assert len(line_landings) == len(plan.solution_sans)
    assert all(frame.arrow_color == "good" for frame in line_landings)

    assert frames[-1].cta == (drama_cfg.cta_top, drama_cfg.cta_bottom)
    assert len(plan.clip_plan.holds) == len(frames)
    assert plan.frame_starts[0] == 0.0
    assert all(hold > 0 for hold in plan.clip_plan.holds)
    assert plan.is_mate is True


def test_plan_skips_wrong_beats_without_an_engine(sample_puzzle, drama_cfg):
    plan = drama.plan_drama(sample_puzzle, [], drama_cfg)
    headlines = [frame.headline for frame in plan.clip_plan.frames]
    assert drama._hook_label(sample_puzzle, drama_cfg) in headlines
    assert drama_cfg.answer_label in headlines
    assert "МАТ!" in headlines


def test_wrong_moves_animate_before_the_red_landing(sample_puzzle, drama_cfg):
    wrongs = _wrong_moves(sample_puzzle)
    plan = drama.plan_drama(sample_puzzle, wrongs, drama_cfg)
    frames = plan.clip_plan.frames
    start_fen = sample_puzzle.puzzle_fen()

    assert len(plan.wrong_frame_indices) == len(wrongs)
    for index in plan.wrong_frame_indices:
        slides = frames[index - drama.SLIDE_STEPS : index]
        assert len(slides) == drama.SLIDE_STEPS
        assert all(frame.moving is not None for frame in slides)
        assert all(frame.fen == start_fen for frame in slides)
        assert frames[index].moving is None
        assert frames[index].annotation == "??"


def test_annotations_mark_wrong_answer_line_and_mate(sample_puzzle, drama_cfg):
    plan = drama.plan_drama(sample_puzzle, _wrong_moves(sample_puzzle), drama_cfg)
    frames = plan.clip_plan.frames

    for index in plan.wrong_frame_indices:
        assert frames[index].annotation == "??"
        assert frames[index].annotation_color == "bad"

    answer = frames[plan.answer_frame_index]
    assert answer.annotation == "!!"
    assert answer.annotation_color == "good"

    assert plan.move_block_starts
    for move_index, start in enumerate(plan.move_block_starts):
        landing = frames[start + drama.SLIDE_STEPS]
        if move_index % 2 == 0:
            assert landing.annotation == "!"
            assert landing.annotation_color == "good"
        else:
            assert landing.annotation is None

    mate = frames[plan.mate_frame_index]
    assert mate.annotation == "#"
    assert mate.annotation_color == "good"


def test_music_volume_is_clearly_audible():
    # The user's reference is music-driven; a bed at 0.24 disappears under the
    # SFX and the phone speaker.
    assert drama.MUSIC_VOLUME >= 0.45


def test_zoom_punch_ramps_over_the_slides(sample_puzzle, drama_cfg):
    plan = drama.plan_drama(sample_puzzle, _wrong_moves(sample_puzzle), drama_cfg)
    frames = plan.clip_plan.frames

    for index in plan.wrong_frame_indices:
        zooms = [frame.zoom for frame in frames[index - drama.SLIDE_STEPS : index]]
        assert zooms == sorted(zooms)
        assert zooms[0] < zooms[-1]
        assert frames[index].zoom == zooms[-1] == 1.06

    assert plan.move_block_starts
    for start in plan.move_block_starts:
        slides = frames[start : start + drama.SLIDE_STEPS]
        zooms = [frame.zoom for frame in slides]
        assert zooms == sorted(zooms)
        assert zooms[0] < zooms[-1]
        assert frames[start + drama.SLIDE_STEPS].zoom == zooms[-1] == 1.02


def test_beat_sync_snaps_move_blocks(sample_puzzle, drama_cfg, tmp_path, monkeypatch):
    seed = tmp_path / "track.wav"
    seed.write_bytes(b"RIFF")  # only needs to exist; the grid is stubbed
    monkeypatch.setattr(drama, "_beat_grid", lambda path: beats.BeatGrid(period=0.5))

    plan = drama.plan_drama(
        sample_puzzle, _wrong_moves(sample_puzzle), drama_cfg, music_path=seed
    )
    # Slide frames stay short, but every narrative block (slides + landing)
    # has to land on a beat.
    index = 0
    while index < len(plan.clip_plan.frames):
        if plan.clip_plan.frames[index].moving is not None:
            start = index
            while (
                index < len(plan.clip_plan.frames)
                and plan.clip_plan.frames[index].moving is not None
            ):
                index += 1
            block = sum(plan.clip_plan.holds[start : index + 1])
            index += 1
        else:
            block = plan.clip_plan.holds[index]
            index += 1
        assert abs(block / 0.5 - round(block / 0.5)) < 1e-6


# --------------------------------------------------------------------------
# Board rendering
# --------------------------------------------------------------------------


def test_mono_board_and_red_arrow_rendering(tmp_path):
    from PIL import Image

    out = board.render_frame(
        board.FrameSpec(
            fen="8/8/8/8/8/8/8/8 w - - 0 1",
            top_text="",
            bottom_text="",
            board_style="mono",
            accent="bad",
            arrow=("a8", "h1"),
            arrow_color="bad",
            headline="НАЙДИ МАТ",
            headline_color="bad",
        ),
        tmp_path / "mono.png",
    )

    with Image.open(out) as img:
        rgb = img.convert("RGB")
        colors = {colour for _, colour in rgb.getcolors(maxcolors=1_000_000)}
        assert board.MONO_LIGHT_SQUARE in colors
        assert board.MONO_DARK_SQUARE in colors

        board_region = rgb.crop(
            (0, board.BOARD_TOP, board.FRAME_W, board.BOARD_TOP + board.BOARD)
        )
        raw = board_region.tobytes()
        assert any(
            raw[i] > 110 and raw[i] > raw[i + 1] * 2 and raw[i] > raw[i + 2] * 2
            for i in range(0, len(raw), 3)
        ), "the red arrow did not render"

        header = rgb.crop((0, 0, board.FRAME_W, board.HEADER_HEIGHT))
        raw = header.tobytes()
        assert any(
            raw[i] > 150 and raw[i] > raw[i + 1] + 50
            for i in range(0, len(raw), 3)
        ), "the red headline did not render"


def test_arrow_colour_palette():
    assert board._arrow_color("good") == board.ARROW_COLOR
    assert board._arrow_color("bad") == board.ARROW_BAD
    assert board._arrow_color("alt") == board.ARROW_ALT
    assert board._highlight_color("bad") == board.HIGHLIGHT_BAD
    assert board._highlight_color("good") == board.HIGHLIGHT_GOOD
    assert board._highlight_color("alt") == board.HIGHLIGHT_ALT
    assert board._highlight_color("neutral") == board.HIGHLIGHT
    assert board._annotation_color("good") == board.ACCENT_GOOD
    assert board._annotation_color("bad") == board.ACCENT_BAD
    assert board._annotation_color("neutral") == board.TEXT_MAIN


def test_annotation_renders_at_the_board_corner(tmp_path):
    from PIL import Image

    out = board.render_frame(
        board.FrameSpec(
            fen="8/8/8/8/8/8/8/8 w - - 0 1",
            top_text="",
            bottom_text="",
            board_style="mono",
            annotation="!!",
            annotation_color="good",
        ),
        tmp_path / "annotation.png",
    )

    with Image.open(out) as img:
        rgb = img.convert("RGB")
        corner = rgb.crop(
            (board.FRAME_W // 2, 0, board.FRAME_W, board.BOARD_TOP)
        )
        raw = corner.tobytes()
        assert any(
            raw[i + 1] > 120 and raw[i + 1] > raw[i] + 30
            for i in range(0, len(raw), 3)
        ), "the green annotation did not render above the board"


# --------------------------------------------------------------------------
# Metadata and render
# --------------------------------------------------------------------------


def test_metadata_has_title_solution_links_and_hashtags(
    sample_puzzle, drama_cfg, tmp_path
):
    plan = drama.plan_drama(
        sample_puzzle, _wrong_moves(sample_puzzle), drama_cfg
    )
    out = tmp_path / "drama.mp4"
    meta = drama.write_metadata(plan, out, drama_cfg)
    text = meta.read_text(encoding="utf-8")

    hook = drama._hook_label(sample_puzzle, drama_cfg)
    assert (hook[:1] + hook[1:].lower()) in text
    assert drama_cfg.lichess_team_url in text
    assert drama_cfg.hashtags[0] in text
    assert "Решение:" in text
    assert plan.solution_sans[-1] in text
    assert "Мотив:" in text


def test_render_drama_without_music_produces_video(
    sample_puzzle, drama_cfg, tmp_path
):
    plan = drama.plan_drama(
        sample_puzzle, _wrong_moves(sample_puzzle), drama_cfg
    )
    out = tmp_path / "drama.mp4"
    result = drama.render_drama(plan, out, music_path=None)
    assert result is not None
    assert result.is_file()
    assert result.stat().st_size > 1000
