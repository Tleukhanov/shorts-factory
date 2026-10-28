"""Tactical-puzzle short: curated Lichess puzzles + voice + CTA.

A tactic short is intentionally simple: the viewer sees a position, gets a few
seconds to think, and the answer is revealed.  All the complexity is in the
quality gate (see :mod:`shorts_clipper.chess.puzzle_db`); the render is just
four beats plus a club call-to-action.
"""

from __future__ import annotations

import dataclasses
import logging
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import ClassVar

from shorts_clipper.chess import puzzle_db
from shorts_clipper.chess.board import FrameSpec
from shorts_clipper.chess.clip import ChessClipPlan, render_clip
from shorts_clipper.utils.ffmpeg_path import ffmpeg_path

log = logging.getLogger(__name__)

THINK_SECONDS = 6.5
CTA_SECONDS = 3.0


@dataclasses.dataclass
class TacticRenderPlan:
    """Everything needed to render one tactic short."""

    puzzle: puzzle_db.Puzzle
    clip_plan: ChessClipPlan
    voice_lines: list[str | None]
    frame_starts: list[float]
    cta_top: str = "Вступай в клуб Senpai"
    cta_bottom: str = "Ссылка в описании"

    _THEME_LABELS: ClassVar[dict[str, str]] = puzzle_db.Puzzle._THEME_LABELS


def _move_san(puzzle: puzzle_db.Puzzle, uci: str) -> str:
    """Convert a solution UCI to SAN in the puzzle position."""
    try:
        import chess

        board = chess.Board(puzzle.puzzle_fen())
        move = chess.Move.from_uci(uci)
        return board.san(move)
    except Exception:
        log.debug("could not convert %s to SAN", uci, exc_info=True)
        return uci


def _side_label(color: str | None) -> str:
    if color == "white":
        return "Ход белых"
    if color == "black":
        return "Ход чёрных"
    return "Чей ход?"


def plan_tactic(
    puzzle: puzzle_db.Puzzle,
    cta_top: str = "Вступай в клуб Senpai",
    cta_bottom: str = "Ссылка в описании",
) -> TacticRenderPlan:
    """Build frame plan and voice script for a tactic short.

    The whole solution line is shown, not just the first move: a deflection
    puzzle that ends in Boden's mate is only satisfying if the viewer sees the
    mate.  Solver moves get the accent, opponent replies stay neutral, and the
    final position is held long enough to read.
    """
    try:
        import chess
    except ImportError:
        return TacticRenderPlan(
            puzzle=puzzle,
            clip_plan=ChessClipPlan(frames=[]),
            voice_lines=[],
            frame_starts=[],
            cta_top=cta_top,
            cta_bottom=cta_bottom,
        )

    color = puzzle.solver_color()
    side = _side_label(color)
    theme = puzzle.theme_label()
    start_fen = puzzle.puzzle_fen() or puzzle.fen
    board = chess.Board(start_fen)

    question = FrameSpec(
        fen=start_fen,
        top_text="Найдёшь здесь тактику?",
        bottom_text=side,
        accent="neutral",
    )
    frames: list[FrameSpec] = [question]
    holds: list[float] = [THINK_SECONDS]
    voice_lines: list[str | None] = ["Найдёшь здесь тактику?"]

    first_san = ""
    last_san = ""
    landing_indices: list[int] = []
    for index, uci in enumerate(puzzle.solution_moves):
        move = chess.Move.from_uci(uci)
        san = board.san(move)
        if index == 0:
            first_san = san
        last_san = san
        src = chess.square_name(move.from_square)
        dst = chess.square_name(move.to_square)
        solver_move = index % 2 == 0
        top = theme.capitalize() if solver_move else "Ответ соперника"
        before_fen = board.fen()
        piece = board.piece_at(move.from_square)
        symbol = piece.symbol() if piece is not None else "p"
        captured = dst if board.piece_at(move.to_square) else None
        hidden = tuple(
            dict.fromkeys(s for s in (src, dst, captured) if s)
        )

        # Six short frames make the piece slide rather than teleport.  The
        # arrow only appears after the piece has landed, like Lichess.
        for step in range(1, 7):
            frames.append(
                FrameSpec(
                    fen=before_fen,
                    top_text=top,
                    bottom_text=san,
                    accent="neutral",
                    moving=(symbol, src, dst, step / 6.0),
                    hidden_squares=hidden,
                )
            )
            holds.append(0.05)
            voice_lines.append(None)

        board.push(move)
        frames.append(
            FrameSpec(
                fen=board.fen(),
                top_text=top,
                bottom_text=san,
                accent="good" if solver_move else "neutral",
                arrow=(src, dst),
                highlight_squares=(src, dst),
            )
        )
        holds.append(1.5 if solver_move else 1.2)
        voice_lines.append(None)
        landing_indices.append(len(frames) - 1)

    # Position after the last move: the mate (or the winning position) itself.
    is_mate = board.is_checkmate()
    final = FrameSpec(
        fen=board.fen(),
        top_text="Мат!" if is_mate else "Позиция выиграна",
        bottom_text=f"Мат — {last_san}" if is_mate else last_san,
        accent="good",
    )
    frames.append(final)
    holds.append(2.6)
    voice_lines.append(None)

    cta = FrameSpec(
        fen="8/8/8/8/8/8/8/8 w - - 0 1",
        top_text="",
        bottom_text="",
        accent="neutral",
        cta=(cta_top, cta_bottom),
    )
    frames.append(cta)
    holds.append(CTA_SECONDS)
    voice_lines.append("Больше тактики — в клубе Senpai.")

    # The first solution move is the hook; the final solver move gets the
    # second voice line, so the mate is named out loud.  Both are attached to
    # the frame where the piece lands, not to a mid-slide animation frame.
    if first_san and landing_indices:
        voice_lines[landing_indices[0]] = f"Есть! {theme} — {first_san}."
    if last_san and landing_indices:
        voice_lines[landing_indices[-1]] = (
            f"И мат — {last_san}!" if is_mate else f"И победа — {last_san}."
        )

    clip_plan = ChessClipPlan(frames=frames, holds=holds)
    frame_starts = _frame_starts(clip_plan)
    return TacticRenderPlan(
        puzzle=puzzle,
        clip_plan=clip_plan,
        voice_lines=voice_lines,
        frame_starts=frame_starts,
        cta_top=cta_top,
        cta_bottom=cta_bottom,
    )


def _frame_starts(plan: ChessClipPlan) -> list[float]:
    starts = [0.0]
    if plan.holds:
        for h in plan.holds[:-1]:
            starts.append(starts[-1] + h)
    return starts


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            if rate:
                return frames / rate
    except Exception:
        log.debug("could not read wav duration", exc_info=True)
    return 0.0


def _synthesize_lines(lines: list[str | None], work: Path) -> list[Path | None]:
    """Synthesize every non-None line to a WAV file."""
    from shorts_clipper.audio.tts import synthesize_voiceover

    results: list[Path | None] = []
    for i, text in enumerate(lines):
        if not text:
            results.append(None)
            continue
        out = work / f"voice_{i}.wav"
        path = synthesize_voiceover(text, out, voice=None, rate="+8%", pitch=None)
        results.append(Path(path) if path else None)
    return results


def _build_voice_track(
    paths: list[Path | None],
    starts: list[float],
    duration: float,
    out: Path,
) -> Path | None:
    """Mix voice WAVs onto a silent stereo track at *starts* seconds."""
    valid = [(p, s) for p, s in zip(paths, starts, strict=False) if p is not None]
    if not valid:
        return None

    ffmpeg = ffmpeg_path()
    work = out.parent
    work.mkdir(parents=True, exist_ok=True)

    # Build a filter graph: base silence + each voice delayed.
    inputs = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    for path, _ in valid:
        inputs += ["-i", str(path)]

    links: list[str] = []
    for idx, (_, start) in enumerate(valid):
        delay_ms = int(round(start * 1000))
        src = f"[{idx + 1}:a]"
        delayed = f"[v{idx}]"
        links.append(
            f"{src}adelay=delays={delay_ms}|{delay_ms}:all=1{delayed}"
        )

    # Chain amix two inputs at a time because amix can take many inputs but the
    # chain keeps the graph readable.
    mix_out = "[aout]"
    if len(valid) == 1:
        delayed = "[v0]"
        links.append(f"[0:a]{delayed}amix=inputs=2:duration=first:normalize=0{mix_out}")
    else:
        # [0:a] mixed with first delayed, then mix result with next delayed, etc.
        current = "[0:a]"
        for idx in range(len(valid)):
            delayed = f"[v{idx}]"
            out_label = f"[m{idx}]" if idx < len(valid) - 1 else mix_out
            links.append(f"{current}{delayed}amix=inputs=2:duration=first:normalize=0{out_label}")
            current = out_label

    filter_complex = ";".join(links)
    cmd = [
        ffmpeg, "-y", "-v", "error",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", mix_out,
        "-t", f"{duration:.3f}",
        "-c:a", "pcm_s16le",
        "-ar", "48000", "-ac", "2",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        log.error("voice track mix failed: %s", (proc.stderr or "")[-800:])
        return None
    return out


def _adjust_holds_for_voice(
    plan: TacticRenderPlan,
    durations: list[float],
) -> tuple[list[float], list[float]]:
    """Return holds and frame starts that fit the synthesized voice lines."""
    if not plan.clip_plan.holds or len(plan.clip_plan.holds) != len(durations):
        return list(plan.clip_plan.holds or []), list(plan.frame_starts)

    new_holds = list(plan.clip_plan.holds)
    for index, duration in enumerate(durations):
        if not duration:
            continue
        # The question frame needs the viewer's thinking time on top of the
        # hook; every other voiced beat just needs a little breathing room.
        padding = 5.0 if index == 0 else 0.8
        new_holds[index] = max(new_holds[index], duration + padding)

    starts = [0.0]
    for h in new_holds[:-1]:
        starts.append(starts[-1] + h)
    return new_holds, starts


def write_metadata(
    plan: TacticRenderPlan,
    out_path: str | Path,
    cfg: puzzle_db.TacticsConfig,
) -> Path:
    """Write title/description file next to the rendered clip."""
    out = Path(out_path)
    meta_path = out.with_suffix(".txt")
    best_move = next((line for line in plan.voice_lines[1:] if line), "")
    lines = [
        f"Найдёшь тактику? | Шахматный клуб {cfg.club_name}",
        "",
        f"Задача дня из базы Lichess (рейтинг {plan.puzzle.rating}).",
        f"Мотив: {plan.puzzle.theme_label()}. {best_move}",
        "",
        "Вступай в клуб:",
        cfg.lichess_team_url,
    ]
    if cfg.whatsapp_url:
        lines += ["", "Чат клуба:", cfg.whatsapp_url]
    lines += ["", " ".join(cfg.hashtags)]
    meta_path.write_text("\n".join(lines), encoding="utf-8")
    return meta_path


def render_tactic(
    plan: TacticRenderPlan,
    out_path: str | Path,
    music_path: str | Path | None = None,
    voice: bool = True,
) -> Path | None:
    """Render a tactic short to *out_path*."""
    from shorts_clipper.chess.clip import add_bed

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_ctx = tempfile.TemporaryDirectory(prefix="tactic_", dir=out.parent)
    work = Path(tmp_ctx.name)

    try:
        voice_files: list[Path | None] = [None] * len(plan.voice_lines)
        voice_durations = [0.0] * len(plan.voice_lines)
        if voice and any(plan.voice_lines):
            voice_files = _synthesize_lines(plan.voice_lines, work)
            voice_durations = [_wav_duration(p) if p else 0.0 for p in voice_files]
            plan.clip_plan.holds, plan.frame_starts = _adjust_holds_for_voice(
                plan, voice_durations
            )

        silent_video = render_clip(plan.clip_plan, work / "silent.mp4", work_dir=work)
        if silent_video is None:
            return None

        if any(voice_files):
            duration = float(plan.clip_plan.duration)
            voice_wav = _build_voice_track(
                voice_files, plan.frame_starts, duration, work / "voice.wav"
            )
            if voice_wav is not None:
                voiced = work / "voiced.mp4"
                cmd = [
                    ffmpeg_path(), "-y", "-v", "error",
                    "-i", str(silent_video),
                    "-i", str(voice_wav),
                    "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    str(voiced),
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if proc.returncode != 0:
                    log.error("voice mux failed: %s", (proc.stderr or "")[-800:])
                    voiced = silent_video
            else:
                voiced = silent_video
        else:
            voiced = silent_video

        if music_path and Path(music_path).is_file():
            final = add_bed(voiced, music_path, out, volume=0.08)
            return final if final.is_file() else voiced
        if voiced != out:
            subprocess.run(
                [ffmpeg_path(), "-y", "-v", "error", "-i", str(voiced), "-c", "copy", str(out)],
                capture_output=True, text=True, timeout=120, check=False,
            )
        return out if out.is_file() else voiced
    finally:
        tmp_ctx.cleanup()
