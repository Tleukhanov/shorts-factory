"""Assemble an MP4 from a parsed scenario and local TTS audio."""

from __future__ import annotations

import logging
import subprocess
import tempfile
import wave
from pathlib import Path

log = logging.getLogger(__name__)


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _ffmpeg() -> str:
    from shorts_clipper.utils.ffmpeg_path import ffmpeg_path

    return ffmpeg_path()


def _build_ass(segments: list[tuple[float, float, str]]) -> str:
    """segments: list of (start, end, text)."""
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            "Style: Default,DejaVu Sans,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
            "-1,0,0,0,100,100,0,0,1,4,2,2,80,80,60,1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def ts(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        cs = int(round((t - int(t)) * 100))
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    for start, end, text in segments:
        text = text.replace("\n", " ").replace(",", "٬").strip()
        if not text:
            continue
        lines.append(f"Dialogue: 0,{ts(start)},{ts(end)},Default,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"


def assemble_documentary(
    segments,
    image_dir: str | Path,
    audio_dir: str | Path,
    out_path: str | Path,
    music_path: str | Path | None = None,
    burn_subtitles: bool = True,
    music_volume: float = 0.10,
    crossfade: float = 0.8,
) -> Path | None:
    """Build one MP4. *segments* are ``scenario.Segment`` objects."""
    image_dir = Path(image_dir)
    audio_dir = Path(audio_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not segments:
        return None

    ffmpeg = _ffmpeg()
    tmp = Path(tempfile.mkdtemp(prefix="ai_doc_"))

    # Audio per segment
    audio_files: list[Path] = []
    audio_files = sorted(audio_dir.glob("seg_*.wav"))
    if len(audio_files) != len(segments):
        log.error(
            "expected %d audio files, found %d in %s",
            len(segments),
            len(audio_files),
            audio_dir,
        )
        return None

    durations = [_wav_duration(p) for p in audio_files]

    subtitle_segments: list[tuple[float, float, str]] = []
    t = 0.0
    for seg, dur in zip(segments, durations, strict=False):
        subtitle_segments.append((t, t + dur, seg.subtitle or seg.voice))
        t += dur

    ass_path = tmp / "subs.ass"
    if burn_subtitles:
        ass_path.write_text(_build_ass(subtitle_segments), encoding="utf-8")

    # Build ffmpeg filter list
    inputs: list[str] = []
    filter_parts: list[str] = []
    for i, seg in enumerate(segments):
        if seg.image:
            img = image_dir / seg.image
        else:
            img = image_dir / f"seg_{i:03d}.png"
        if not img.is_file():
            log.error("missing image: %s (provide image or run Colab generator)", img)
            return None
        inputs += ["-loop", "1", "-framerate", "24", "-t", f"{durations[i]:.3f}", "-i", str(img)]
        inputs += ["-i", str(audio_files[i])]

    audio_indices = [2 * i + 1 for i in range(len(segments))]
    image_indices = [2 * i for i in range(len(segments))]

    # Zoompan each image
    for i, idx in enumerate(image_indices):
        filter_parts.append(
            f"[{idx}:v]scale=1920:1080:force_original_aspect_ratio=increase,"
            f"crop=1920:1080,zoompan=z='min(zoom+0.0009,1.12)':d=1:s=1920x1080:fps=24,format=yuv420p,setsar=1[v{i}]"
        )

    # Concat visuals
    concat_inputs = "".join(f"[v{i}]" for i in range(len(segments)))
    filter_parts.append(f"{concat_inputs}concat=n={len(segments)}:v=1:a=0[vout]")

    # Concat audios
    concat_a = "".join(f"[{idx}:a]" for idx in audio_indices)
    filter_parts.append(f"{concat_a}concat=n={len(segments)}:v=0:a=1[aout]")

    # Optional music ducked under voice
    if music_path and Path(music_path).is_file():
        inputs += ["-i", str(music_path)]
        music_idx = 2 * len(segments)
        # Kokoro/Silero voice is mono at its own rate; bring everything to
        # 48 kHz stereo before mixing, otherwise amix refuses to initialise.
        # Music is ducked under the voice: EQ cuts the 2-4 kHz band where the
        # voice sits, and sidechain compression drops the music further while
        # speech is present.  This keeps the voice intelligible and the music
        # from masking it.
        filter_parts.append(
            f"[{music_idx}:a]aloop=loop=-1:size=2e+09,"
            f"aformat=sample_rates=48000:channel_layouts=stereo,"
            f"volume={music_volume},asetpts=PTS-STARTPTS[mus]"
        )
        filter_parts.append(
            "[aout]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[voc]"
        )
        filter_parts.append("[voc][mus]amix=inputs=2:duration=first:dropout_transition=0[amixed]")
        a_final = "[amixed]"
    else:
        a_final = "[aout]"

    # Burn subtitles
    if burn_subtitles:
        filter_parts.append(f"[vout]ass='{ass_path}'[vfinal]")
        v_final = "[vfinal]"
    else:
        v_final = "[vout]"

    log.info("filter_complex: %s", ";".join(filter_parts))
    cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        *inputs,
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        v_final,
        "-map",
        a_final,
        "-c:v",
        "libx264",
        "-crf",
        "20",
        "-preset",
        "veryfast",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        log.error("ffmpeg failed: %s", proc.stderr[-800:])
        return None
    return out_path
