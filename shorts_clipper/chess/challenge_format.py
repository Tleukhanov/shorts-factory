"""Club challenge short: tournament games turned into viewer puzzles.

A tournament game is a believable context: real players, real ratings, real
moments.  This format scans those games for positions where one move is clearly
better than everything else, filters out positions that are too easy or come
from very low-rated players, and renders them as "Сможешь сыграть как 2000?"
shorts with a club call-to-action.

The heavy selection still depends on :mod:`shorts_clipper.chess.challenges`,
which needs an engine to distinguish the best move from the second-best.  When
no engine is available the format honestly produces nothing rather than guessing.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import random
import re
import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar

from shorts_clipper.chess import challenges, clip, lichess
from shorts_clipper.chess.board import FrameSpec
from shorts_clipper.chess.tactics import (
    _build_voice_track,
    _frame_starts,
    _synthesize_lines,
    _wav_duration,
)
from shorts_clipper.pipeline.stock_dedup import script_hash
from shorts_clipper.utils.ffmpeg_path import ffmpeg_path

log = logging.getLogger(__name__)

THINK_SECONDS = 5.0
PAUSE_SECONDS = 1.5
REVEAL_SECONDS = 3.5
CTA_SECONDS = 3.0


@dataclasses.dataclass
class ChallengeConfig:
    """Configuration for the club-challenge format."""

    club_name: str = "Senpai"
    lichess_team_url: str = "https://lichess.org/team/senpai"
    whatsapp_url: str = ""
    hashtags: tuple[str, ...] = ("#шахматы", "#задача", "#shorts")
    min_player_rating: int = 1500
    target_player_rating: int = 2000
    member_min_rating: int = 1800
    critical_cp: int = 200
    min_ply: int = 10
    max_games: int = 20
    gap_cp_min: int = 300
    cta_top: str = "Вступай в клуб Senpai"
    cta_bottom: str = "Ссылка в описании"
    team_id: str | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> ChallengeConfig:
        path = Path(path)
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        if "hashtags" in raw and isinstance(raw["hashtags"], list):
            raw["hashtags"] = tuple(raw["hashtags"])
        return cls(**raw)


@dataclasses.dataclass
class ChallengeRenderPlan:
    """Everything needed to render one club-challenge short."""

    challenge: challenges.Challenge
    headers: dict
    player_rating: int
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
    return ChallengeRenderPlan._THEME_LABELS.get(color, color)


def _player_name(headers: dict, color: str) -> str:
    key = "White" if color == "white" else "Black"
    raw = headers.get(key, "")
    name = str(raw or "").split(",")[0].strip()
    return name or f"{_side_label(color)}"


def _parse_elo(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mover_rating(headers: dict, color: str, fallback: int) -> int:
    key = "WhiteElo" if color == "white" else "BlackElo"
    rating = _parse_elo(headers.get(key))
    return rating if rating is not None else fallback


def _team_id_from_url(url: str) -> str | None:
    match = re.search(r"/team/([a-zA-Z0-9_-]+)", url or "")
    return match.group(1) if match else None


def tournament_id_from_args(path_args: list[str]) -> str:
    """Extract a Lichess tournament id from the CLI ``path`` argument."""
    if not path_args:
        return ""
    return lichess._parse_tournament_id(path_args[0])  # noqa: SLF001


def _game_length(game: object) -> int:
    try:
        return len(list(game.mainline_moves())) // 2
    except Exception:
        return 0


def _eval_caption(challenge: challenges.Challenge) -> str | None:
    """`оценка +0.6` from the mover's side, in Russian."""
    try:
        value = challenge.mover_cp / 100.0
    except Exception:
        return None
    if challenge.mate_in:
        return f"оценка: мат в {challenge.mate_in}"
    return f"оценка: {value:+.1f}"


def find_challenges_in_games(
    games,
    cfg: ChallengeConfig,
    club_members: list[str] | None = None,
) -> list[tuple[challenges.Challenge, dict, int]]:
    """Scan tournament games for publishable challenge positions.

    Returns a list of ``(challenge, headers, mover_rating)`` sorted best first.
    The sorting rewards a large engine gap and gives a bonus to games where a
    high-rated club member is playing, because those are the moments viewers can
    relate to the club.
    """
    members = {m.lower() for m in (club_members or [])}
    games = list(games)
    if cfg.max_games and len(games) > cfg.max_games:
        rng = random.Random(42)
        rng.shuffle(games)
        games = games[: cfg.max_games]

    scored: list[tuple[challenges.Challenge, dict, int, int]] = []
    seen: set[str] = set()

    for game in games:
        headers = dict(getattr(game, "headers", {}) or {})
        white_elo = _parse_elo(headers.get("WhiteElo"))
        black_elo = _parse_elo(headers.get("BlackElo"))

        # Skip games between very low-rated players unless a rating is missing,
        # in which case we let the engine decide whether the position is worth it.
        if white_elo is not None and black_elo is not None:
            if white_elo < cfg.min_player_rating and black_elo < cfg.min_player_rating:
                continue

        found = challenges.find_challenges(
            game,
            min_gap_cp=cfg.gap_cp_min,
            min_ply=cfg.min_ply,
            limit=3,
        )
        if not found:
            continue

        for challenge in found:
            # One-move mates are a gift, not a puzzle; ``challenges`` already
            # filters them, but the contract is worth repeating here.
            if challenge.mate_in is not None and challenge.mate_in < 2:
                continue

            key = script_hash(f"{challenge.fen} {challenge.best_uci}")
            if key in seen:
                continue
            seen.add(key)

            mover_rating = _mover_rating(headers, challenge.color, cfg.target_player_rating)
            score = challenge.gap_cp

            # Boost games that feature a strong club member -- these are the
            # moments the channel can credibly claim came from the club.
            if members:
                for key_name in ("White", "Black"):
                    name = str(headers.get(key_name, "")).split(",")[0].strip().lower()
                    if not name or name not in members:
                        continue
                    elo = white_elo if key_name == "White" else black_elo
                    if elo is not None and elo >= cfg.member_min_rating:
                        score += 500
                        break

            scored.append((challenge, headers, mover_rating, score))

    scored.sort(key=lambda item: item[3], reverse=True)
    return [(c, h, r) for c, h, r, _ in scored]


def plan_challenge_game(
    challenge: challenges.Challenge,
    game_headers: dict,
    cfg: ChallengeConfig,
) -> ChallengeRenderPlan:
    """Build frame plan and voice script for one club challenge short."""
    headers = dict(game_headers or {})
    color = challenge.color
    side = _side_label(color)
    player = _player_name(headers, color)
    rating = _mover_rating(headers, color, cfg.target_player_rating)
    move = challenge.best_san
    src = challenge.best_uci[:2]
    dst = challenge.best_uci[2:4]
    seconds = int(round(THINK_SECONDS + PAUSE_SECONDS))

    hook_voice = f"Сможешь сыграть как {rating}? Найди ход!"
    reveal_voice = f"Ход {move}. {player} нашёл это за {seconds} секунд."
    cta_voice = "Брось вызов клубу — ссылка в описании."

    question = FrameSpec(
        fen=challenge.fen,
        top_text=f"Сможешь сыграть как {rating}?",
        bottom_text=side,
        accent="neutral",
    )
    pause = FrameSpec(
        fen=challenge.fen,
        top_text="Найди ход!",
        bottom_text=side,
        accent="neutral",
    )
    answer = FrameSpec(
        fen=challenge.fen,
        top_text=move,
        bottom_text=f"{player} — {rating}",
        accent="good",
        arrow=(src, dst),
        highlight_squares=(src, dst),
        eval_text=_eval_caption(challenge),
    )
    cta = FrameSpec(
        fen="8/8/8/8/8/8/8/8 w - - 0 1",
        top_text="",
        bottom_text="",
        accent="neutral",
        cta=(cfg.cta_top, cfg.cta_bottom),
    )

    clip_plan = clip.ChessClipPlan(
        frames=[question, pause, answer, cta],
        holds=[THINK_SECONDS, PAUSE_SECONDS, REVEAL_SECONDS, CTA_SECONDS],
    )

    voice_lines = [hook_voice, None, reveal_voice, cta_voice]
    return ChallengeRenderPlan(
        challenge=challenge,
        headers=headers,
        player_rating=rating,
        clip_plan=clip_plan,
        voice_lines=voice_lines,
        frame_starts=_frame_starts(clip_plan),
        cta_top=cfg.cta_top,
        cta_bottom=cfg.cta_bottom,
    )


def _adjust_holds_for_challenge(
    plan: ChallengeRenderPlan,
    durations: list[float],
) -> tuple[list[float], list[float]]:
    """Stretch holds so each voiced frame has room to finish."""
    if not plan.clip_plan.holds or len(plan.clip_plan.holds) != len(durations):
        return list(plan.clip_plan.holds or []), list(plan.frame_starts)

    new_holds = list(plan.clip_plan.holds)
    # Question frame: keep the board on screen after the hook finishes.
    if durations[0]:
        new_holds[0] = max(new_holds[0], durations[0] + 4.0)
    # Answer frame is index 2 because the pause frame has no voice line.
    if durations[2]:
        new_holds[2] = max(new_holds[2], durations[2] + 0.8)
    if durations[3]:
        new_holds[3] = max(new_holds[3], durations[3] + 0.8)

    starts = [0.0]
    for h in new_holds[:-1]:
        starts.append(starts[-1] + h)
    return new_holds, starts


def write_metadata(
    plan: ChallengeRenderPlan,
    out_path: str | Path,
    cfg: ChallengeConfig,
) -> Path:
    """Write title/description file next to the rendered clip."""
    import types

    out = Path(out_path)
    meta_path = out.with_suffix(".txt")
    white = _player_name(plan.headers, "white")
    black = _player_name(plan.headers, "black")
    game_url = lichess.game_url(types.SimpleNamespace(headers=plan.headers)) or ""

    lines = [
        f"Сможешь сыграть как {plan.player_rating}? | Клуб {cfg.club_name}",
        "",
        f"Задача из партии {white} — {black}.",
        f"Найди ход {plan.challenge.best_san}.",
    ]
    if game_url:
        lines += ["", f"Партия: {game_url}"]
    lines += [
        "",
        "Брось вызов клубу:",
        cfg.lichess_team_url,
    ]
    if cfg.whatsapp_url:
        lines += ["", "Чат клуба:", cfg.whatsapp_url]
    lines += ["", " ".join(cfg.hashtags)]
    meta_path.write_text("\n".join(lines), encoding="utf-8")
    return meta_path


def render_challenge(
    plan: ChallengeRenderPlan,
    out_path: str | Path,
    music_path: str | Path | None = None,
    voice: bool = True,
) -> Path | None:
    """Render a club-challenge short to *out_path*."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_ctx = tempfile.TemporaryDirectory(prefix="challenge_", dir=out.parent)
    work = Path(tmp_ctx.name)

    try:
        voice_files: list[Path | None] = [None] * len(plan.voice_lines)
        voice_durations = [0.0] * len(plan.voice_lines)
        if voice and any(plan.voice_lines):
            voice_files = _synthesize_lines(plan.voice_lines, work)
            voice_durations = [_wav_duration(p) if p else 0.0 for p in voice_files]
            plan.clip_plan.holds, plan.frame_starts = _adjust_holds_for_challenge(
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
                    ffmpeg_path(),
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(silent_video),
                    "-i",
                    str(voice_wav),
                    "-map",
                    "0:v",
                    "-map",
                    "1:a",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
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
            final = clip.add_bed(voiced, music_path, out, volume=0.08)
            return final if final.is_file() else voiced
        if voiced != out:
            subprocess.run(
                [ffmpeg_path(), "-y", "-v", "error", "-i", str(voiced), "-c", "copy", str(out)],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        return out if out.is_file() else voiced
    finally:
        tmp_ctx.cleanup()
