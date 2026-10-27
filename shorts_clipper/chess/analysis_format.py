"""Real-game analysis short: decisive moment + voiceover + club CTA.

A tournament or team produces dozens of games, most of them uninteresting.
This module picks the single worst decision per game, ranks them across the
whole event, and renders the best ones as vertical shorts with the same
hook-explanation-CTA shape the tactics format uses.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import random
import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar

from shorts_clipper.chess import analysis, clip, lichess
from shorts_clipper.chess.board import FrameSpec
from shorts_clipper.chess.tactics import (
    _adjust_holds_for_voice,
    _build_voice_track,
    _frame_starts,
    _synthesize_lines,
    _wav_duration,
)
from shorts_clipper.pipeline.stock_dedup import script_hash
from shorts_clipper.utils.ffmpeg_path import ffmpeg_path

log = logging.getLogger(__name__)

HOOK_SECONDS = 3.0
REVEAL_SECONDS = 3.5
AFTER_SECONDS = 2.0
CTA_SECONDS = 3.0


@dataclasses.dataclass
class AnalysisConfig:
    """Configuration for the real-game analysis format."""

    club_name: str = "Senpai"
    lichess_team_url: str = "https://lichess.org/team/senpai"
    whatsapp_url: str = ""
    hashtags: tuple[str, ...] = ("#шахматы", "#разбор", "#shorts")
    critical_cp: int = 200
    min_ply: int = 10
    min_moves: int = 10
    max_games: int = 50
    cta_top: str = "Вступай в клуб Senpai"
    cta_bottom: str = "Ссылка в описании"
    team_id: str | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> AnalysisConfig:
        path = Path(path)
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        if "hashtags" in raw and isinstance(raw["hashtags"], list):
            raw["hashtags"] = tuple(raw["hashtags"])
        return cls(**raw)


@dataclasses.dataclass
class AnalysisRenderPlan:
    """Everything needed to render one real-game analysis short."""

    decision: analysis.Decision
    clip_plan: clip.ChessClipPlan
    voice_lines: list[str | None]
    frame_starts: list[float]
    cta_top: str = "Вступай в клуб Senpai"
    cta_bottom: str = "Ссылка в описании"

    _THEME_LABELS: ClassVar[dict[str, str]] = {
        "white": "белые",
        "black": "чёрные",
    }


def _side_label(color: str) -> str:
    return AnalysisRenderPlan._THEME_LABELS.get(color, color)


def _player_name(headers, color: str) -> str:
    key = "White" if color == "white" else "Black"
    raw = headers.get(key, "")
    name = str(raw or "").split(",")[0].strip()
    return name or f"{_side_label(color)}"


def _loss_voice(decision: analysis.Decision) -> str:
    if decision.is_mated:
        mate = decision.mate_in or 1
        return f"Мат через {mate}."
    return f"Минус {decision.lost_piece_value:.1f} за один ход."


def plan_analysis(
    decision: analysis.Decision,
    cfg: AnalysisConfig | None = None,
) -> AnalysisRenderPlan:
    """Build frame plan and voice script for one decisive moment."""
    cfg = cfg or AnalysisConfig()
    headers = dict(decision.header or {})
    white = _player_name(headers, "white")
    black = _player_name(headers, "black")
    side = _side_label(decision.color)

    title = f"Ход {decision.move_number}… {decision.san}"
    loss = decision.caption()

    hook = FrameSpec(
        fen=decision.fen_before,
        top_text="Зевок в партии клуба",
        bottom_text=f"{white} — {black}",
        accent="neutral",
    )
    reveal = FrameSpec(
        fen=decision.fen_before,
        top_text=title,
        bottom_text=loss,
        accent="bad",
        arrow=(decision.uci[:2], decision.uci[2:4]),
        highlight_squares=(decision.uci[:2], decision.uci[2:4]),
    )
    after = FrameSpec(
        fen=decision.fen_after,
        top_text=f"{side} отдали перевес",
        bottom_text="Такие разборы — каждый день",
        accent="bad",
    )
    cta = FrameSpec(
        fen="8/8/8/8/8/8/8/8 w - - 0 1",
        top_text="",
        bottom_text="",
        accent="neutral",
        cta=(cfg.cta_top, cfg.cta_bottom),
    )

    clip_plan = clip.ChessClipPlan(
        frames=[hook, reveal, after, cta],
        holds=[HOOK_SECONDS, REVEAL_SECONDS, AFTER_SECONDS, CTA_SECONDS],
    )

    hook_voice = "Найдёшь ошибку в партии клуба?"
    reveal_voice = f"{white} — {black}. Ход {decision.move_number}, {decision.san}. {_loss_voice(decision)}"
    cta_voice = f"Больше разборов — в клубе {cfg.club_name}."

    voice_lines = [hook_voice, reveal_voice, None, cta_voice]
    return AnalysisRenderPlan(
        decision=decision,
        clip_plan=clip_plan,
        voice_lines=voice_lines,
        frame_starts=_frame_starts(clip_plan),
        cta_top=cfg.cta_top,
        cta_bottom=cfg.cta_bottom,
    )


def write_metadata(
    plan: AnalysisRenderPlan,
    out_path: str | Path,
    cfg: AnalysisConfig,
) -> Path:
    """Write title/description file next to the rendered clip."""
    out = Path(out_path)
    meta_path = out.with_suffix(".txt")
    headers = dict(plan.decision.header or {})
    white = _player_name(headers, "white")
    black = _player_name(headers, "black")

    lines = [
        f"Разбор партии | {white} — {black} | Клуб {cfg.club_name}",
        "",
        f"Решающий момент: ход {plan.decision.move_number} — {plan.decision.san}.",
        f"{plan.decision.caption()}",
        "",
        "Вступай в клуб:",
        cfg.lichess_team_url,
    ]
    if cfg.whatsapp_url:
        lines += ["", "Чат клуба:", cfg.whatsapp_url]
    lines += ["", " ".join(cfg.hashtags)]
    meta_path.write_text("\n".join(lines), encoding="utf-8")
    return meta_path


def render_analysis(
    plan: AnalysisRenderPlan,
    out_path: str | Path,
    music_path: str | Path | None = None,
    voice: bool = True,
) -> Path | None:
    """Render a real-game analysis short to *out_path*."""
    from shorts_clipper.chess.clip import add_bed

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_ctx = tempfile.TemporaryDirectory(prefix="analysis_", dir=out.parent)
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

        silent_video = clip.render_clip(plan.clip_plan, work / "silent.mp4", work_dir=work)
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


def _game_length(game: object) -> int:
    """Full moves in a game, 0 if the object is unusable."""
    try:
        return len(list(game.mainline_moves())) // 2
    except Exception:
        return 0


def _has_club_member(game: object, members: set[str]) -> bool:
    """True when at least one player is in the club roster."""
    headers = dict(getattr(game, "headers", {}) or {})
    for key in ("White", "Black"):
        name = str(headers.get(key) or "").split(",")[0].strip().lower()
        if name and name in members:
            return True
    return False


def select_moments(
    games: list[object],
    *,
    count: int,
    cfg: AnalysisConfig | None = None,
    club_members: list[str] | None = None,
    used: set[str] | None = None,
) -> tuple[list[analysis.Decision], dict[str, int]]:
    """Pick the best decisive moments across *games*.

    Returns ``(decisions, stats)``.  *stats* reports how many games were
    scanned, skipped for being too short, skipped because they had no moment
    above the threshold, and filtered out because no club member played.
    """
    cfg = cfg or AnalysisConfig()
    used = used or set()
    members = {m.lower() for m in (club_members or [])}
    decisions: list[analysis.Decision] = []
    stats = {
        "scanned": 0,
        "too_short": 0,
        "no_moment": 0,
        "not_member": 0,
        "duplicate": 0,
        "sampled": 0,
    }

    eligible: list[object] = []
    for game in games:
        stats["scanned"] += 1
        if _game_length(game) < cfg.min_moves:
            stats["too_short"] += 1
            continue
        if members and not _has_club_member(game, members):
            stats["not_member"] += 1
            continue
        eligible.append(game)

    if cfg.max_games and len(eligible) > cfg.max_games:
        rng = random.Random(42)
        rng.shuffle(eligible)
        eligible = eligible[: cfg.max_games]
    stats["sampled"] = len(eligible)

    for game in eligible:
        found = analysis.find_decisions(
            game,
            critical_cp=cfg.critical_cp,
            min_ply=cfg.min_ply,
            limit=1,
        )
        if not found:
            stats["no_moment"] += 1
            continue

        decision = found[0]
        key = script_hash(f"{decision.fen_before} {decision.uci}")
        if key in used:
            stats["duplicate"] += 1
            continue
        decisions.append(decision)

    decisions.sort(key=lambda d: d.mover_loss_cp, reverse=True)
    return decisions[: max(count, 1)], stats


def tournament_id_from_args(path_args: list[str]) -> str:
    """Extract a Lichess tournament id from the CLI ``path`` argument."""
    if not path_args:
        return ""
    return lichess._parse_tournament_id(path_args[0])  # noqa: SLF001
