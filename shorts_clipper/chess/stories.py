"""Human-centric chess stories: tournament recaps, member profiles, behind-the-scenes.

This format is different from the board-based formats.  It is a vertical short
built from text beats, a background visual, optional presenter avatar and TTS
voiceover.  The presenter asset is a placeholder by design: drop a real image or
video into ``assets/presenter/`` and update ``presenter_asset`` in the config to
swap it in.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from shorts_clipper.chess import lichess
from shorts_clipper.chess.tactics import (
    _build_voice_track,
    _synthesize_lines,
    _wav_duration,
)
from shorts_clipper.utils.ffmpeg_path import ffmpeg_path

log = logging.getLogger(__name__)

FRAME_W = 1080
FRAME_H = 1920
FPS = 30

# Russian narration pacing used when TTS is unavailable or for estimates.
_WORDS_PER_SECOND = 2.6
_MIN_HOLD = 2.0
_CTA_HOLD = 3.0
_TEXT_PAD = 80
_AVATAR_W = 280
_AVATAR_H = 350
_AVATAR_MARGIN = 40

_FONT_PATHS = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def _load_font(size: int):
    """Return a TrueType font that covers basic text, or PIL default."""
    try:
        from PIL import ImageFont

        for path in _FONT_PATHS:
            if Path(path).is_file():
                try:
                    return ImageFont.truetype(str(path), size)
                except Exception:
                    continue
        try:
            import matplotlib

            bundled = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
            if bundled.is_file():
                return ImageFont.truetype(str(bundled), size)
        except Exception:
            pass
        return ImageFont.load_default()
    except Exception:
        log.debug("font load failed", exc_info=True)
        return None


@dataclasses.dataclass
class StoryConfig:
    """Configuration for the human-story chess format."""

    club_name: str = "Senpai"
    lichess_team_url: str = "https://lichess.org/team/senpai"
    whatsapp_url: str = ""
    hashtags: tuple[str, ...] = ("#шахматы", "#истории", "#shorts")
    presenter_asset: str = "assets/presenter/placeholder.png"
    background_color: str = "#1a1a2e"
    text_color: str = "#ffffff"
    accent_color: str = "#e6be5c"
    cta_top: str = "Вступай в клуб Senpai"
    cta_bottom: str = "Ссылка в описании"
    beats: dict[str, str] | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> StoryConfig:
        path = Path(path)
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        if "hashtags" in raw and isinstance(raw["hashtags"], list):
            raw["hashtags"] = tuple(raw["hashtags"])
        return cls(**raw)


@dataclasses.dataclass
class StoryBeat:
    """One narrative beat in a story short."""

    kind: str
    text: str
    asset_path: str | Path | None = None


@dataclasses.dataclass
class StoryPlan:
    """Everything needed to render one story short."""

    beats: list[StoryBeat]
    holds: list[float]
    voice_segments: list[tuple[str | None, float, float]]
    cta_top: str = "Вступай в клуб Senpai"
    cta_bottom: str = "Ссылка в описании"
    cfg: StoryConfig | None = None

    @property
    def total_duration(self) -> float:
        return float(sum(self.holds))

    @property
    def frame_starts(self) -> list[float]:
        starts = [0.0]
        for h in self.holds[:-1]:
            starts.append(starts[-1] + h)
        return starts


def _estimate_speech_duration(text: str | None) -> float:
    """Estimate how long *text* takes to speak, in seconds."""
    if not text:
        return 0.0
    words = len(text.split())
    return max(0.8, words / _WORDS_PER_SECOND)


def _format_date(raw: str | None) -> str:
    """Best-effort pretty date from an ISO-ish string."""
    if not raw:
        return "недавно"
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return str(raw)[:10]


def _avg_rating(players: list[dict[str, Any]]) -> int:
    ratings: list[int] = []
    for p in players:
        score = p.get("score")
        if isinstance(score, dict):
            rating = score.get("rating")
        else:
            rating = p.get("rating")
        try:
            ratings.append(int(rating))
        except Exception:
            continue
    if not ratings:
        return 0
    return int(sum(ratings) / len(ratings))


def _podium(players: list[dict[str, Any]]) -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []
    for p in players[:3]:
        name = p.get("name") or p.get("username") or "?"
        score = p.get("score") or {}
        rating = score.get("rating") if isinstance(score, dict) else p.get("rating")
        try:
            rating = int(rating)
        except Exception:
            rating = 0
        results.append((str(name), rating))
    return results


def _best_moment(stats: dict[str, Any] | None, players: list[dict[str, Any]]) -> str:
    """Pick a memorable stat line for the payoff beat."""
    stats = stats or {}
    berserk = stats.get("berserkCount")
    if berserk:
        return f"Берсерк — {berserk} раз!"
    if len(players) > 10:
        return f"{len(players)} игроков сразились за первое место."
    return "Решающие партии до последнего хода."


def build_tournament_recap(
    tournament_meta: dict[str, Any],
    cfg: StoryConfig | None = None,
) -> list[StoryBeat]:
    """Auto-generate story beats from Lichess tournament metadata."""
    cfg = cfg or StoryConfig()
    name = tournament_meta.get("fullName") or tournament_meta.get("name") or "Турнир клуба"
    players_raw = tournament_meta.get("players", {})
    if isinstance(players_raw, list):
        players = players_raw
    else:
        players = players_raw.get("players", []) or []
    stats = tournament_meta.get("stats", {})
    podium = _podium(players)
    winner_name, winner_rating = podium[0] if podium else ("?", 0)

    templates = cfg.beats or {}
    hook_text = templates.get(
        "hook",
        "{tournament_name}: кто победил?",
    ).format(tournament_name=name)
    variant = tournament_meta.get("variant", {})
    if isinstance(variant, dict):
        variant_name = variant.get("name", "Стандарт")
    else:
        variant_name = str(variant).capitalize() or "Стандарт"
    context_text = templates.get(
        "context",
        "{date} · {format} · {players} игроков · средний рейтинг {avg_rating}",
    ).format(
        date=_format_date(tournament_meta.get("startsAt")),
        format=variant_name,
        players=len(players),
        avg_rating=_avg_rating(players),
    )
    if podium:
        payoff_text = templates.get(
            "payoff",
            "Подиум: 1. {first_name} ({first_rating}), 2. {second_name} ({second_rating}), "
            "3. {third_name} ({third_rating}). {best_moment}",
        ).format(
            first_name=podium[0][0],
            first_rating=podium[0][1],
            second_name=podium[1][0] if len(podium) > 1 else "?",
            second_rating=podium[1][1] if len(podium) > 1 else 0,
            third_name=podium[2][0] if len(podium) > 2 else "?",
            third_rating=podium[2][1] if len(podium) > 2 else 0,
            best_moment=_best_moment(stats, players),
        )
    else:
        payoff_text = "Итоги турнира уже в нашей группе."

    cta_text = templates.get(
        "cta",
        "Присоединяйся к клубу {club_name}. {whatsapp_url}",
    ).format(club_name=cfg.club_name, whatsapp_url=cfg.whatsapp_url or "")

    return [
        StoryBeat(kind="hook", text=hook_text),
        StoryBeat(kind="context", text=context_text),
        StoryBeat(kind="payoff", text=payoff_text),
        StoryBeat(kind="cta", text=cta_text),
    ]


def build_member_story(
    username: str,
    member_info: dict[str, Any] | None = None,
    cfg: StoryConfig | None = None,
) -> list[StoryBeat]:
    """Auto-generate a short player profile from Lichess team member info.

    When the Lichess API does not return enough data, pass a JSON sidecar with
    keys such as ``rating``, ``title``, ``favorite_opening`` or ``best_result``.
    """
    cfg = cfg or StoryConfig()
    info = member_info or {}
    templates = cfg.beats or {}

    display = info.get("username") or username
    title = info.get("title")
    if title:
        display = f"{title} {display}"

    perfs = info.get("perfs", {})
    classical = perfs.get("classical", {}).get("rating") if isinstance(perfs, dict) else None
    rapid = perfs.get("rapid", {}).get("rating") if isinstance(perfs, dict) else None
    blitz = perfs.get("blitz", {}).get("rating") if isinstance(perfs, dict) else None
    rating = classical or rapid or blitz or info.get("rating") or "?"

    country = info.get("profile", {}).get("country") if isinstance(info.get("profile"), dict) else None
    country = country or info.get("country", "")
    best = info.get("best_result") or "участник клубных турниров"

    hook_text = templates.get("member_hook", "Игрок недели: {username}").format(
        username=display
    )
    context_text = templates.get(
        "member_context",
        "Рейтинг: {rating} · {country}",
    ).format(rating=rating, country=country or "клубный боец")
    payoff_text = templates.get("member_payoff", "{best}").format(best=best)
    cta_text = templates.get(
        "member_cta",
        "Подписывайся на истории клуба {club_name}.",
    ).format(club_name=cfg.club_name)

    return [
        StoryBeat(kind="hook", text=hook_text),
        StoryBeat(kind="context", text=context_text),
        StoryBeat(kind="payoff", text=payoff_text),
        StoryBeat(kind="cta", text=cta_text),
    ]


def _resolve_background_asset(
    beat: StoryBeat,
    cfg: StoryConfig,
) -> str | Path | None:
    """Return the background asset for *beat*, falling back to the config default."""
    if beat.asset_path:
        return beat.asset_path
    return cfg.presenter_asset if cfg.presenter_asset else None


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Convert ``#rrggbb`` to an RGB tuple."""
    value = (value or "#000000").lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except Exception:
        return (26, 26, 46)


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    """Wrap *text* into lines that fit *max_width* at *font* size."""
    try:
        from PIL import Image, ImageDraw

        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            bbox = probe.textbbox((0, 0), candidate, font=font)
            if bbox[2] - bbox[0] <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines
    except Exception:
        return text.splitlines() or [text]


def _render_text_frame(
    text: str,
    cfg: StoryConfig,
    background_asset: str | Path | None = None,
    presenter_asset: str | Path | None = None,
    font_size: int = 84,
) -> Any:
    """Render a single 1080x1920 frame with centred text and optional avatar."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (FRAME_W, FRAME_H), _hex_to_rgb(cfg.background_color))

    # Optional background image/video frame.
    if background_asset:
        bg_path = Path(background_asset)
        if bg_path.is_file():
            try:
                ext = bg_path.suffix.lower()
                if ext in (".mp4", ".mov", ".webm", ".mkv"):
                    # Extract one representative frame from the video.
                    with tempfile.TemporaryDirectory(prefix="story_bg_") as tmp:
                        probe = Path(tmp) / "frame.png"
                        cmd = [
                            ffmpeg_path(), "-y", "-v", "error",
                            "-ss", "0.5", "-i", str(bg_path),
                            "-vframes", "1", "-q:v", "2", str(probe),
                        ]
                        subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                        if probe.is_file():
                            with Image.open(probe) as bg:
                                img = _fit_background(bg)
                else:
                    with Image.open(bg_path) as bg:
                        img = _fit_background(bg)
            except Exception:
                log.debug("background asset render failed", exc_info=True)

    # Darken image backgrounds so white text remains readable.
    overlay = Image.new("RGBA", (FRAME_W, FRAME_H), (0, 0, 0, 120))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)
    font = _load_font(font_size)

    # Scale the font down until the text block fits.
    while font_size > 32:
        font = _load_font(font_size)
        lines = _wrap_text(text, font, FRAME_W - 2 * _TEXT_PAD)
        line_h = max(1, font_size + 12)
        block_h = len(lines) * line_h
        if block_h <= FRAME_H - 500:
            break
        font_size -= 6

    lines = _wrap_text(text, font, FRAME_W - 2 * _TEXT_PAD)
    line_h = max(1, font_size + 12)
    block_h = len(lines) * line_h
    y = (FRAME_H - block_h) // 2

    text_rgb = _hex_to_rgb(cfg.text_color)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (FRAME_W - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, fill=text_rgb, font=font)
        y += line_h

    if presenter_asset:
        img = _overlay_avatar(img, presenter_asset)

    return img


def _fit_background(bg: Any) -> Any:
    """Resize and crop a background image to fill the 1080x1920 frame."""
    from PIL import Image

    bg = bg.convert("RGBA")
    src_w, src_h = bg.size
    target_ratio = FRAME_W / FRAME_H
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        new_h = FRAME_H
        new_w = int(new_h * src_ratio)
    else:
        new_w = FRAME_W
        new_h = int(new_w / src_ratio)

    bg = bg.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - FRAME_W) // 2
    top = (new_h - FRAME_H) // 2
    return bg.crop((left, top, left + FRAME_W, top + FRAME_H))


def _overlay_avatar(img: Any, presenter_asset: str | Path) -> Any:
    """Paste a rounded-corner avatar into the bottom-right corner."""
    from PIL import Image, ImageDraw

    avatar_path = Path(presenter_asset)
    if not avatar_path.is_file():
        return img

    try:
        with Image.open(avatar_path) as av:
            av = av.convert("RGBA")
            av = av.resize((_AVATAR_W, _AVATAR_H), Image.Resampling.LANCZOS)
    except Exception:
        log.debug("avatar load failed", exc_info=True)
        return img

    mask = Image.new("L", (_AVATAR_W, _AVATAR_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, _AVATAR_W, _AVATAR_H), radius=24, fill=255
    )
    av.putalpha(mask)

    x = FRAME_W - _AVATAR_W - _AVATAR_MARGIN
    y = FRAME_H - _AVATAR_H - _AVATAR_MARGIN
    img.paste(av, (x, y), av)
    return img


def plan_story(
    beats: list[StoryBeat],
    cfg: StoryConfig | None = None,
    voice: bool = True,
) -> StoryPlan:
    """Build a render plan with per-beat holds derived from voice durations.

    When *voice* is ``True`` the function tries to synthesise each beat to get
    real durations; otherwise it estimates from word count.  A missing TTS
    engine always degrades to estimates rather than failing.
    """
    cfg = cfg or StoryConfig()
    if not beats:
        beats = [StoryBeat(kind="hook", text=cfg.cta_top)]

    durations: list[float] = []
    if voice:
        with tempfile.TemporaryDirectory(prefix="story_plan_") as tmp:
            work = Path(tmp)
            lines: list[str | None] = [b.text for b in beats]
            try:
                paths = _synthesize_lines(lines, work)
                durations = [_wav_duration(p) if p else 0.0 for p in paths]
            except Exception:
                log.debug("story plan TTS failed, using estimates", exc_info=True)
                durations = []

    if len(durations) != len(beats):
        durations = [_estimate_speech_duration(b.text) for b in beats]

    holds: list[float] = []
    for i, beat in enumerate(beats):
        base = durations[i]
        if beat.kind == "cta":
            holds.append(max(_CTA_HOLD, base + 0.8))
        elif beat.kind == "hook":
            holds.append(max(_MIN_HOLD + 1.0, base + 1.2))
        else:
            holds.append(max(_MIN_HOLD, base + 0.8))

    segments: list[tuple[str | None, float, float]] = []
    start = 0.0
    for beat, h in zip(beats, holds, strict=False):
        segments.append((beat.text, start, h))
        start += h

    return StoryPlan(
        beats=beats,
        holds=holds,
        voice_segments=segments,
        cta_top=cfg.cta_top,
        cta_bottom=cfg.cta_bottom,
        cfg=cfg,
    )


def _draw_beat_frames(
    plan: StoryPlan,
    cfg: StoryConfig,
    work: Path,
    presenter_asset: str | Path | None = None,
) -> list[Path]:
    """Render a PNG for every beat and return the ordered paths."""
    presenter = presenter_asset if presenter_asset and Path(presenter_asset).is_file() else None
    paths: list[Path] = []
    for i, beat in enumerate(plan.beats):
        bg = _resolve_background_asset(beat, cfg)
        img = _render_text_frame(
            beat.text,
            cfg,
            background_asset=bg,
            presenter_asset=presenter,
        )
        png = work / f"frame_{i}.png"
        img.save(png, "PNG")
        paths.append(png)
    return paths


def write_metadata(
    plan: StoryPlan,
    out_path: str | Path,
    cfg: StoryConfig,
) -> Path:
    """Write title/description file next to the rendered clip."""
    out = Path(out_path)
    meta_path = out.with_suffix(".txt")

    hook = next((b.text for b in plan.beats if b.kind == "hook"), "")
    lines = [
        f"{hook} | Клуб {cfg.club_name}",
        "",
        "История шахматиста и клуба.",
        "",
        "Вступай в клуб:",
        cfg.lichess_team_url,
    ]
    if cfg.whatsapp_url:
        lines += ["", "Чат клуба:", cfg.whatsapp_url]
    lines += ["", " ".join(cfg.hashtags)]
    meta_path.write_text("\n".join(lines), encoding="utf-8")
    return meta_path


def render_story(
    plan: StoryPlan,
    out_path: str | Path,
    music_path: str | Path | None = None,
    voice: bool = True,
) -> Path | None:
    """Render a human-story short to *out_path*."""
    from shorts_clipper.chess.clip import add_bed

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_ctx = tempfile.TemporaryDirectory(prefix="story_", dir=out.parent)
    work = Path(tmp_ctx.name)

    try:
        cfg = plan.cfg or StoryConfig()
        presenter = cfg.presenter_asset if Path(cfg.presenter_asset).is_file() else None

        voice_files: list[Path | None] = [None] * len(plan.beats)
        voice_durations = [0.0] * len(plan.beats)
        if voice and any(b.text for b in plan.beats):
            voice_files = _synthesize_lines([b.text for b in plan.beats], work)
            voice_durations = [_wav_duration(p) if p else 0.0 for p in voice_files]
            # Stretch holds when real speech is longer than the estimate.
            for i, dur in enumerate(voice_durations):
                if dur and dur > plan.holds[i] - 0.5:
                    plan.holds[i] = dur + 0.8

        frames = _draw_beat_frames(plan, cfg, work, presenter_asset=presenter)
        silent_video = _frames_to_video(frames, plan.holds, work / "silent.mp4")
        if silent_video is None or not silent_video.is_file():
            return None

        if any(voice_files):
            duration = plan.total_duration
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
                    log.error("story voice mux failed: %s", (proc.stderr or "")[-800:])
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


def _frames_to_video(
    frames: list[Path],
    holds: list[float],
    out: Path,
    fps: int = FPS,
) -> Path | None:
    """Concatenate still frames with explicit durations into an mp4."""
    if not frames:
        return None
    work = out.parent
    listing = work / "story_concat.txt"
    lines: list[str] = []
    for i, png in enumerate(frames):
        lines.append(f"file '{png.as_posix()}'")
        lines.append(f"duration {max(0.08, float(holds[i])):.3f}")
    lines.append(f"file '{frames[-1].as_posix()}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = [
        ffmpeg_path(), "-y", "-v", "error",
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf", "format=yuv420p",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-r", str(fps), "-shortest",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        log.error("story concat failed: %s", (proc.stderr or "")[-600:])
        return None
    return out


def tournament_id_from_args(path_args: list[str]) -> str:
    """Extract a Lichess tournament id from the CLI ``path`` argument."""
    if not path_args:
        return ""
    return lichess._parse_tournament_id(path_args[0])  # noqa: SLF001


def parse_beats_from_json(path: str | Path) -> list[StoryBeat]:
    """Load beats from a JSON file.

    Accepts either a list of ``{"kind", "text", "asset_path?"}`` objects or a
    dict with a ``beats`` key holding that list.
    """
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        items = raw.get("beats", [])
    else:
        items = list(raw)
    return [
        StoryBeat(
            kind=item.get("kind", "context"),
            text=item.get("text", ""),
            asset_path=item.get("asset_path"),
        )
        for item in items
    ]
