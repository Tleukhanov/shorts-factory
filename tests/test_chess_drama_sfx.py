"""Zoom-punch and SFX tests for the drama format.

The visual punch and the synthesized cues are both easy to ship silently broken:
a zoom that clamps to 1.0 renders an identical frame, and an SFX mix that fails
open still produces a valid video.  These tests assert the frame actually
changes, the clamp holds, the WAVs are real audio, and a full render with a bed
and SFX completes.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from shorts_clipper.chess import board, drama, puzzle_db, sfx

FIXTURE = Path(__file__).with_suffix("").parent / "fixtures" / "puzzles.csv.zst"


@pytest.fixture(scope="module")
def sample_puzzle(tmp_path_factory):
    cfg = puzzle_db.TacticsConfig(
        db_path=FIXTURE,
        cache_path=tmp_path_factory.mktemp("drama_sfx") / "selected.json",
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


def _spec(**overrides) -> board.FrameSpec:
    fields = {
        "fen": "r1bq1rk1/ppp2ppp/2n5/3p4/3P4/2P5/PP1Q1PPP/RNB1K1NR w KQ - 0 1",
        "top_text": "",
        "bottom_text": "",
        "board_style": "mono",
        "headline": "НАЙДИ МАТ",
    }
    fields.update(overrides)
    return board.FrameSpec(**fields)


def _wrong_moves(puzzle, count=2):
    import chess

    position = chess.Board(puzzle.puzzle_fen())
    answer = chess.Move.from_uci(puzzle.solution_moves[0])
    out = []
    for move in position.legal_moves:
        if move == answer:
            continue
        out.append(drama.WrongMove(move.uci(), position.san(move), -50 * len(out)))
        if len(out) >= count:
            break
    assert len(out) == count
    return out


def _stub_music(path: Path, seconds: float = 2.0) -> Path:
    """A quiet valid WAV so the bed mixer has something real to read."""
    rate = 48_000
    t = np.arange(int(rate * seconds)) / rate
    tone = 0.2 * np.sin(2 * np.pi * 220 * t)
    frames = np.column_stack((tone, tone))
    pcm = (np.clip(frames, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return path


# --------------------------------------------------------------------------
# Zoom punches
# --------------------------------------------------------------------------


def test_zoom_changes_the_rendered_frame(tmp_path):
    plain = board.render_frame(_spec(zoom=1.0), tmp_path / "plain.png")
    punched = board.render_frame(_spec(zoom=1.06), tmp_path / "punched.png")
    assert plain.read_bytes() != punched.read_bytes()


def test_zoom_is_clamped_to_the_readable_range(tmp_path):
    maximum = board.render_frame(_spec(zoom=board.ZOOM_MAX), tmp_path / "max.png")
    too_much = board.render_frame(_spec(zoom=4.0), tmp_path / "too_much.png")
    assert maximum.read_bytes() == too_much.read_bytes()

    plain = board.render_frame(_spec(zoom=1.0), tmp_path / "plain.png")
    below_one = board.render_frame(_spec(zoom=0.4), tmp_path / "below.png")
    assert plain.read_bytes() == below_one.read_bytes()


def test_cta_card_is_never_zoomed(tmp_path):
    plain = board.render_frame(
        _spec(cta=("Вступай в клуб", "Ссылка в описании"), zoom=1.0),
        tmp_path / "plain.png",
    )
    punched = board.render_frame(
        _spec(cta=("Вступай в клуб", "Ссылка в описании"), zoom=1.12),
        tmp_path / "punched.png",
    )
    assert plain.read_bytes() == punched.read_bytes()


def test_plan_sets_punch_on_the_decisive_beats(sample_puzzle):
    cfg = drama.DramaConfig(music_path="", beat_sync=False)
    plan = drama.plan_drama(sample_puzzle, _wrong_moves(sample_puzzle), cfg)
    frames = plan.clip_plan.frames

    assert frames[0].zoom == 1.0
    assert all(frames[index].zoom == 1.06 for index in plan.wrong_frame_indices)
    assert frames[plan.answer_frame_index].zoom == 1.08
    assert frames[plan.mate_frame_index].zoom == 1.05
    assert frames[-1].cta is not None and frames[-1].zoom == 1.0

    landing_zooms = [
        frames[index + drama.SLIDE_STEPS].zoom
        for index in plan.move_block_starts
        if index + drama.SLIDE_STEPS < len(frames)
        and frames[index + drama.SLIDE_STEPS].headline is None
    ]
    assert landing_zooms
    assert set(landing_zooms) <= {1.0, 1.02}
    assert 1.02 in landing_zooms


# --------------------------------------------------------------------------
# SFX synthesis
# --------------------------------------------------------------------------


def _wav_info(path: Path) -> tuple[float, int, int, int]:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
        return frames / rate, handle.getnchannels(), handle.getsampwidth(), rate


def _wav_peak(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        raw = handle.readframes(handle.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    return float(np.max(np.abs(samples)))


def test_synthesize_sfx_writes_audible_stereo_wavs(tmp_path):
    paths = sfx.synthesize_sfx(tmp_path / "sfx")

    expected = {
        "wrong_buzz": (0.30, 0.45),
        "correct_ding": (0.40, 0.55),
        "whoosh": (0.20, 0.35),
        "impact": (0.25, 0.40),
    }
    assert set(paths) == set(expected)
    for name, (low, high) in expected.items():
        path = paths[name]
        assert path.is_file() and path.stat().st_size > 1000
        duration, channels, width, rate = _wav_info(path)
        assert low <= duration <= high, f"{name}: {duration}s"
        assert channels == 2
        assert width == 2
        assert rate == sfx.SAMPLE_RATE
        assert _wav_peak(path) < 0.8


# --------------------------------------------------------------------------
# Full render
# --------------------------------------------------------------------------


def test_render_drama_with_music_and_sfx_produces_video(sample_puzzle, tmp_path):
    music = _stub_music(tmp_path / "bed.wav")
    cfg = drama.DramaConfig(music_path=str(music), beat_sync=False)
    plan = drama.plan_drama(sample_puzzle, _wrong_moves(sample_puzzle), cfg)

    assert plan.wrong_frame_indices
    assert plan.answer_frame_index >= 0
    assert plan.move_block_starts

    out = tmp_path / "drama_sfx.mp4"
    result = drama.render_drama(plan, out, music_path=music, sfx=True)
    assert result is not None
    assert result.is_file()
    assert result.stat().st_size > 1000
