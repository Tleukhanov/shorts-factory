"""Viral puzzle-drama short: hook, wrong moves, reveal, full line, CTA.

The format borrows the structure of the fast puzzle edits that do well on
Shorts/TikTok: a big meme headline over a grayscale board, a couple of plausible
wrong moves crossed out in red, the correct move in green, then the whole
solution -- mate included -- and a club call-to-action.  There is no voiceover:
the on-screen text is the message, so the clip is music and sound only.

Everything here is deterministic.  Selection comes from the curated Lichess
puzzle DB (the same quality gate the tactic format uses), wrong moves come from
a MultiPV engine search, and the frame plan is a pure function of the puzzle and
the config.  Music is optional; without a bed the clip still renders.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from shorts_clipper.chess import beats, engine, puzzle_db
from shorts_clipper.chess.board import FrameSpec
from shorts_clipper.chess.clip import ChessClipPlan, add_bed, render_clip

log = logging.getLogger(__name__)

# Frame holds.  The hook is the only slow beat (the viewer has to read the
# position); wrong moves and slide frames are fast cuts; the mate and the CTA
# sit long enough to be read.  Beat snapping re-times all of them when a track
# is available, so these are the shape of the edit, not its final duration.
HOOK_SECONDS = 2.4
WRONG_SECONDS = 1.2
ANSWER_SECONDS = 1.8
SLIDE_STEPS = 5
SLIDE_SECONDS = 0.07
LANDING_SECONDS = 1.1
FINAL_SECONDS = 2.6
CTA_SECONDS = 2.8

MUSIC_SUFFIXES = (".wav", ".mp3", ".m4a", ".ogg")
DEFAULT_MUSIC_DIR = "data/music"
GENERATED_MUSIC_NAME = "generated_phonk_loop.wav"


@dataclasses.dataclass
class DramaConfig:
    """Publishing and visual settings for the drama format."""

    club_name: str = "Senpai"
    lichess_team_url: str = "https://lichess.org/team/senpai"
    whatsapp_url: str = ""
    hashtags: tuple[str, ...] = ("#шахматы", "#мат", "#senpai", "#shorts")
    music_path: str = "data/music/phonk.wav"
    beat_sync: bool = True
    max_wrong_moves: int = 2
    hook_label: str = "НАЙДИ МАТ"
    wrong_labels: list[str] = dataclasses.field(
        default_factory=lambda: ["НЕ ТОТ ХОД", "МИМО", "ТАК НЕ НАДО"]
    )
    answer_label: str = "ВОТ ОТВЕТ"
    cta_top: str = "Вступай в клуб Senpai"
    cta_bottom: str = "Ссылка в описании"
    board_style: str = "mono"

    @classmethod
    def from_file(cls, path: str | Path) -> DramaConfig:
        """Load config from JSON, or return defaults when the file is absent."""
        path = Path(path)
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        if "hashtags" in raw and isinstance(raw["hashtags"], list):
            raw["hashtags"] = tuple(raw["hashtags"])
        raw.setdefault("music_path", cls.music_path)
        return cls(**raw)


@dataclasses.dataclass(frozen=True)
class WrongMove:
    """A plausible but incorrect move, with the engine's score for it."""

    uci: str
    san: str
    eval_cp: int


@dataclasses.dataclass
class DramaRenderPlan:
    """Everything needed to render one drama short."""

    puzzle: puzzle_db.Puzzle
    clip_plan: ChessClipPlan
    wrong_moves: list[WrongMove]
    solution_sans: list[str]
    frame_starts: list[float]
    is_mate: bool = False


def _side_label(color: str | None) -> str:
    if color == "white":
        return "Ход белых"
    if color == "black":
        return "Ход чёрных"
    return "Чей ход?"


def find_wrong_moves(
    puzzle: puzzle_db.Puzzle,
    count: int = 2,
    depth: int | None = None,
) -> list[WrongMove]:
    """The best moves that are *not* the answer, as :class:`WrongMove`s.

    One MultiPV search in the puzzle position.  The first line is the best move
    and is dropped; the rest are the moves the edit presents as traps.  Without
    an engine there is nothing honest to show, so the list is empty and the plan
    simply skips the wrong-move beats.
    """
    try:
        import chess
    except ImportError:
        return []

    fen = puzzle.puzzle_fen()
    if not fen:
        return []
    try:
        board = chess.Board(fen)
    except Exception:
        log.debug("bad puzzle position for %s", puzzle.id, exc_info=True)
        return []

    try:
        lines = engine.top_moves(fen, count + 1, depth_override=depth)
    except Exception:
        log.debug("wrong-move search failed for %s", puzzle.id, exc_info=True)
        return []
    if not lines:
        return []

    out: list[WrongMove] = []
    # The curated answer must never appear as a red "wrong move": on a puzzle
    # where the engine's top line differs from the published solution, the raw
    # runner-up list can contain it, and a red arrow on the correct move is a
    # clip that contradicts itself.
    answers = set(puzzle.solution_moves)
    for uci, evaluation in lines[1 : count + 1]:
        if uci in answers:
            continue
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            continue
        if move not in board.legal_moves:
            continue
        out.append(
            WrongMove(
                uci=uci,
                san=board.san(move),
                eval_cp=int(evaluation.cp),
            )
        )
    return out


def _frame_starts(plan: ChessClipPlan) -> list[float]:
    starts = [0.0]
    if plan.holds:
        for hold in plan.holds[:-1]:
            starts.append(starts[-1] + hold)
    return starts


@functools.lru_cache(maxsize=8)
def _cached_grid(path: str, _mtime: float) -> beats.BeatGrid | None:
    """Measure a track's beat grid once per run (mtime invalidates the cache)."""
    return beats.beat_grid(path)


def _beat_grid(path: Path) -> beats.BeatGrid | None:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    return _cached_grid(str(path), mtime)


def _empty_plan(puzzle: puzzle_db.Puzzle) -> DramaRenderPlan:
    return DramaRenderPlan(
        puzzle=puzzle,
        clip_plan=ChessClipPlan(frames=[]),
        wrong_moves=[],
        solution_sans=[],
        frame_starts=[],
    )


def _slide_frames(
    *,
    fen: str,
    san: str,
    piece_symbol: str,
    src: str,
    dst: str,
    hidden: tuple[str, ...],
    board_style: str,
) -> list[FrameSpec]:
    """Five interpolated frames for one move, so the piece slides in."""
    return [
        FrameSpec(
            fen=fen,
            top_text="",
            bottom_text=san,
            accent="neutral",
            moving=(piece_symbol, src, dst, step / SLIDE_STEPS),
            hidden_squares=hidden,
            board_style=board_style,
        )
        for step in range(1, SLIDE_STEPS + 1)
    ]


def _snap_blocks(frames: list[FrameSpec], holds: list[float], grid) -> list[float]:
    """Snap whole move blocks to the beat, not the individual slide frames.

    A move block is the run of ``moving`` frames plus its landing frame.  The
    block as a whole should land on a beat, while the slide frames inside it
    stay short -- otherwise every 0.07s slide is stretched to a full beat and
    the piece crawls across the board.
    """
    blocks: list[tuple[int, int]] = []
    index = 0
    while index < len(frames):
        if frames[index].moving is not None:
            start = index
            while index < len(frames) and frames[index].moving is not None:
                index += 1
            if index < len(frames) and frames[index].arrow is not None:
                blocks.append((start, index))
                index += 1
                continue
            for single in range(start, index):
                blocks.append((single, single))
            continue
        blocks.append((index, index))
        index += 1

    block_holds = [sum(holds[start : end + 1]) for start, end in blocks]
    snapped = beats.snap_holds(block_holds, start_seconds=0.0, grid=grid)

    result: list[float] = []
    for (start, end), block_hold in zip(blocks, snapped, strict=False):
        if start == end:
            result.append(block_hold)
            continue
        slides = end - start
        slide_hold = min(
            SLIDE_SECONDS,
            max(0.02, (block_hold - 0.2) / max(1, slides)),
        )
        landing = max(0.15, block_hold - slide_hold * slides)
        result.extend([slide_hold] * slides)
        result.append(landing)
    return result


def plan_drama(
    puzzle: puzzle_db.Puzzle,
    wrong_moves: list[WrongMove],
    cfg: DramaConfig,
    music_path: str | Path | None = None,
) -> DramaRenderPlan:
    """Build the hook -> wrong -> answer -> line -> mate -> CTA frame plan.

    *music_path* overrides ``cfg.music_path`` for beat snapping only; it does
    not change the rendered bed, which :func:`render_drama` owns.
    """
    try:
        import chess
    except ImportError:
        return _empty_plan(puzzle)

    start_fen = puzzle.puzzle_fen() or puzzle.fen
    try:
        board = chess.Board(start_fen)
    except Exception:
        log.debug("could not parse puzzle position for %s", puzzle.id, exc_info=True)
        return _empty_plan(puzzle)

    frames: list[FrameSpec] = []
    holds: list[float] = []

    # Beat 1: the hook.  The position is untouched; no arrow, no highlight.
    frames.append(
        FrameSpec(
            fen=start_fen,
            top_text="",
            bottom_text=_side_label(puzzle.solver_color()),
            accent="neutral",
            board_style=cfg.board_style,
            headline=cfg.hook_label,
            headline_color="bad",
        )
    )
    holds.append(HOOK_SECONDS)

    # Beat 2: plausible wrong moves, red arrow and red squares.
    applied_wrongs: list[WrongMove] = []
    for index, wrong in enumerate(wrong_moves[: max(0, cfg.max_wrong_moves)]):
        try:
            move = chess.Move.from_uci(wrong.uci)
        except ValueError:
            continue
        if move not in board.legal_moves:
            continue
        applied_wrongs.append(wrong)
        src = chess.square_name(move.from_square)
        dst = chess.square_name(move.to_square)
        after = board.copy(stack=False)
        san = wrong.san or after.san(move)
        after.push(move)
        if cfg.wrong_labels:
            label = cfg.wrong_labels[index % len(cfg.wrong_labels)]
        else:
            label = "НЕ ТОТ ХОД"
        frames.append(
            FrameSpec(
                fen=after.fen(),
                top_text="",
                bottom_text=san,
                accent="bad",
                highlight_squares=(src, dst),
                arrow=(src, dst),
                board_style=cfg.board_style,
                arrow_color="bad",
                headline=label,
                headline_color="bad",
            )
        )
        holds.append(WRONG_SECONDS)

    if not puzzle.solution_moves:
        return _empty_plan(puzzle)

    # Beat 3: the answer, board *before* the move and a green arrow.
    try:
        best_move = chess.Move.from_uci(puzzle.solution_moves[0])
        if best_move not in board.legal_moves:
            return _empty_plan(puzzle)
        best_san = board.san(best_move)
    except Exception:
        log.debug("could not read the answer for %s", puzzle.id, exc_info=True)
        return _empty_plan(puzzle)
    best_src = chess.square_name(best_move.from_square)
    best_dst = chess.square_name(best_move.to_square)
    frames.append(
        FrameSpec(
            fen=start_fen,
            top_text="",
            bottom_text=best_san,
            accent="good",
            highlight_squares=(best_src, best_dst),
            arrow=(best_src, best_dst),
            board_style=cfg.board_style,
            arrow_color="good",
            headline=cfg.answer_label,
            headline_color="good",
        )
    )
    holds.append(ANSWER_SECONDS)

    # Beat 4: the full solution line, every move green -- the line is forced,
    # and the last move is the mate the clip has been promising.
    line_board = board.copy(stack=False)
    solution_sans: list[str] = []
    for uci in puzzle.solution_moves:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in line_board.legal_moves:
            break
        san = line_board.san(move)
        solution_sans.append(san)
        before_fen = line_board.fen()
        src = chess.square_name(move.from_square)
        dst = chess.square_name(move.to_square)
        piece = line_board.piece_at(move.from_square)
        symbol = piece.symbol() if piece is not None else "p"
        captured = dst if line_board.is_capture(move) else None
        hidden = tuple(dict.fromkeys(s for s in (src, dst, captured) if s))

        frames.extend(
            _slide_frames(
                fen=before_fen,
                san=san,
                piece_symbol=symbol,
                src=src,
                dst=dst,
                hidden=hidden,
                board_style=cfg.board_style,
            )
        )
        holds.extend([SLIDE_SECONDS] * SLIDE_STEPS)

        line_board.push(move)
        frames.append(
            FrameSpec(
                fen=line_board.fen(),
                top_text="",
                bottom_text=san,
                accent="good",
                highlight_squares=(src, dst),
                arrow=(src, dst),
                board_style=cfg.board_style,
                arrow_color="good",
            )
        )
        holds.append(LANDING_SECONDS)

    # Beat 5: the final position.  A real mate is called out; anything else is
    # the solved position rather than a claim that the game is over.
    is_mate = line_board.is_checkmate()
    final_headline = "МАТ!" if is_mate else "ХОД НАЙДЕН"
    final_bottom = (
        f"Мат — {solution_sans[-1]}" if is_mate and solution_sans else ""
    )
    frames.append(
        FrameSpec(
            fen=line_board.fen(),
            top_text="",
            bottom_text=final_bottom,
            accent="good",
            board_style=cfg.board_style,
            headline=final_headline,
            headline_color="good",
        )
    )
    holds.append(FINAL_SECONDS)

    # Beat 6: the club card.
    frames.append(
        FrameSpec(
            fen="8/8/8/8/8/8/8/8 w - - 0 1",
            top_text="",
            bottom_text="",
            accent="neutral",
            board_style=cfg.board_style,
            cta=(cfg.cta_top, cfg.cta_bottom),
        )
    )
    holds.append(CTA_SECONDS)

    # Cut the edit to the music when there is a track to measure.  A missing,
    # unreadable or beatless file leaves the planned timing exactly as it is.
    bed = Path(music_path) if music_path is not None else Path(cfg.music_path or "")
    if cfg.beat_sync and bed and bed.is_file():
        grid = _beat_grid(bed)
        if grid is not None and grid.usable:
            try:
                holds = _snap_blocks(frames, holds, grid)
            except Exception:
                log.debug("could not snap drama holds to the beat", exc_info=True)

    clip_plan = ChessClipPlan(frames=frames, holds=holds)
    return DramaRenderPlan(
        puzzle=puzzle,
        clip_plan=clip_plan,
        wrong_moves=applied_wrongs,
        solution_sans=solution_sans,
        frame_starts=_frame_starts(clip_plan),
        is_mate=is_mate,
    )


def write_metadata(
    plan: DramaRenderPlan,
    out_path: str | Path,
    cfg: DramaConfig,
) -> Path:
    """Write the title/description/links/hashtags next to the clip."""
    out = Path(out_path)
    meta_path = out.with_suffix(".txt")
    hook_title = (cfg.hook_label[:1] + cfg.hook_label[1:].lower()).strip()
    lines = [
        f"{hook_title} | Шахматный клуб {cfg.club_name}",
        "",
        f"Задача из базы Lichess (рейтинг {plan.puzzle.rating}).",
        f"Мотив: {plan.puzzle.theme_label()}.",
    ]
    if plan.solution_sans:
        lines.append(f"Решение: {' '.join(plan.solution_sans)}.")
    if plan.wrong_moves:
        lines.append(
            "Ловушки: " + ", ".join(wrong.san for wrong in plan.wrong_moves) + "."
        )
    lines += [
        "",
        "Вступай в клуб:",
        cfg.lichess_team_url,
    ]
    if cfg.whatsapp_url:
        lines += ["", "Чат клуба:", cfg.whatsapp_url]
    lines += ["", " ".join(cfg.hashtags)]
    meta_path.write_text("\n".join(lines), encoding="utf-8")
    return meta_path


def render_drama(
    plan: DramaRenderPlan,
    out_path: str | Path,
    music_path: str | Path | None = None,
    volume: float = 0.16,
) -> Path | None:
    """Render *plan* to *out_path* with an optional music bed; no TTS voice."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not plan.clip_plan.frames:
        log.warning("Drama plan has no frames")
        return None

    with tempfile.TemporaryDirectory(prefix="drama_", dir=out.parent) as tmp:
        work = Path(tmp)
        silent = render_clip(plan.clip_plan, work / "silent.mp4", work_dir=work)
        if silent is None:
            return None
        bed = Path(music_path) if music_path is not None else None
        if bed is not None and bed.is_file():
            mixed = add_bed(silent, bed, out, volume=volume)
            return mixed if mixed.is_file() else silent
        return add_bed(silent, None, out)


def music_candidates(music_dir: str | Path = DEFAULT_MUSIC_DIR) -> list[Path]:
    """Audio files in *music_dir*, sorted so a run is deterministic."""
    directory = Path(music_dir)
    if not directory.is_dir():
        return []
    return sorted(
        (p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in MUSIC_SUFFIXES),
        key=lambda p: p.name,
    )


def _generate_phonk_fallback(music_dir: str | Path) -> Path | None:
    """Synthesize the licence-free phonk loop when no real track is present."""
    directory = Path(music_dir)
    destination = directory / GENERATED_MUSIC_NAME
    if destination.is_file():
        return destination
    script = Path(__file__).resolve().parents[2] / "scripts" / "make_phonk.py"
    if not script.is_file():
        return None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "--out",
                str(destination),
                "--duration",
                "45",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except Exception:
        log.debug("phonk generation failed", exc_info=True)
        return None
    if proc.returncode != 0 or not destination.is_file():
        log.warning("phonk fallback failed: %s", (proc.stderr or "")[-400:])
        return None
    return destination


def resolve_music(
    cfg: DramaConfig,
    explicit: str | Path | None = None,
    no_music: bool = False,
    music_dir: str | Path = DEFAULT_MUSIC_DIR,
    allow_generate: bool = True,
) -> Path | None:
    """Pick the bed: explicit file, config path, first track, then phonk fallback.

    Returns ``None`` only when the caller asked for silence or no usable track
    could be found and generation was disabled or failed.  The clip renders
    without music, which is a valid output rather than an error.
    """
    if no_music:
        return None
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if cfg.music_path:
        candidates.append(Path(cfg.music_path))
    candidates.extend(music_candidates(music_dir))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    if allow_generate:
        return _generate_phonk_fallback(music_dir)
    return None
