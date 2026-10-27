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
AFTER_REVEAL_SECONDS = 1.5
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
    """Build frame plan and voice script for a tactic short."""
    color = puzzle.solver_color()
    side = _side_label(color)
    first_solution = puzzle.solution_moves[0]
    san = _move_san(puzzle, first_solution)
    src = first_solution[:2]
    dst = first_solution[2:4]
    theme = puzzle.theme_label()

    hook_voice = "Найдёшь здесь тактику?"
    reveal_voice = f"Есть! {theme} — {san}."
    cta_voice = "Больше тактики — в клубе Senpai."

    question = FrameSpec(
        fen=puzzle.puzzle_fen() or puzzle.fen,
        top_text="Найдёшь здесь тактику?",
        bottom_text=side,
        accent="neutral",
    )
    reveal = FrameSpec(
        fen=puzzle.puzzle_fen() or puzzle.fen,
        top_text=theme.capitalize(),
        bottom_text=san,
        accent="good",
        arrow=(src, dst),
        highlight_squares=(src, dst),
    )
    after = FrameSpec(
        fen=_after_fen(puzzle) or (puzzle.puzzle_fen() or puzzle.fen),
        top_text=theme.capitalize(),
        bottom_text="Такие задачи — каждый день",
        accent="good",
    )
    cta = FrameSpec(
        fen="8/8/8/8/8/8/8/8 w - - 0 1",
        top_text="",
        bottom_text="",
        accent="neutral",
        cta=(cta_top, cta_bottom),
    )

    clip_plan = ChessClipPlan(
        frames=[question, reveal, after, cta],
        holds=[THINK_SECONDS, 2.5, AFTER_REVEAL_SECONDS, CTA_SECONDS],
    )

    # Voice lines align with frame starts.
    voice_lines = [hook_voice, reveal_voice, None, cta_voice]
    frame_starts = _frame_starts(clip_plan)
    return TacticRenderPlan(
        puzzle=puzzle,
        clip_plan=clip_plan,
        voice_lines=voice_lines,
        frame_starts=frame_starts,
        cta_top=cta_top,
        cta_bottom=cta_bottom,
    )


def _after_fen(puzzle: puzzle_db.Puzzle) -> str | None:
    """FEN after the first solution move and its best reply (if any)."""
    try:
        import chess

        board = chess.Board(puzzle.puzzle_fen())
        moves = puzzle.solution_moves
        if not moves:
            return None
        board.push(chess.Move.from_uci(moves[0]))
        if len(moves) > 1:
            board.push(chess.Move.from_uci(moves[1]))
        return board.fen()
    except Exception:
        log.debug("could not build after-FEN", exc_info=True)
        return None


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
    # Question frame: give the viewer 5 seconds to think after the hook finishes.
    if durations[0]:
        new_holds[0] = max(new_holds[0], durations[0] + 5.0)
    # Reveal and CTA frames: small padding after the voice line.
    if durations[1]:
        new_holds[1] = max(new_holds[1], durations[1] + 0.8)
    if durations[3]:
        new_holds[3] = max(new_holds[3], durations[3] + 0.8)

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
    best_move = plan.voice_lines[1] or ""
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
