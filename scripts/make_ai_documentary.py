#!/usr/bin/env python3
"""Produce an AI documentary video from a markdown scenario."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from shorts_clipper.ai_doc import tts_local
from shorts_clipper.ai_doc.assemble import assemble_documentary
from shorts_clipper.ai_doc.config import AiDocumentaryConfig
from shorts_clipper.ai_doc.scenario import load_scenario

log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="Markdown scenario file")
    parser.add_argument("--image-dir", default=None, help="Directory with segment images")
    parser.add_argument("--out-dir", default=None, help="Output directory")
    parser.add_argument("--config", default=None, help="JSON config override")
    parser.add_argument("--voice", default=None, help="TTS voice id")
    parser.add_argument("--language", default=None, help="'en' or 'ru'")
    parser.add_argument("--no-subtitles", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    cfg = AiDocumentaryConfig.from_file(args.config) if args.config else AiDocumentaryConfig()
    if args.language:
        cfg.language = args.language
    if args.voice:
        if cfg.language == "ru":
            cfg.voice_ru = args.voice
        else:
            cfg.voice_en = args.voice
    if args.no_subtitles:
        cfg.burn_subtitles = False

    scenario = Path(args.scenario)
    if not scenario.is_file():
        print(f"❌ scenario not found: {scenario}", file=sys.stderr)
        return 2
    meta, segments = load_scenario(scenario)
    image_dir = (
        Path(args.image_dir) if args.image_dir else scenario.with_suffix("").parent / "images"
    )
    audio_dir = image_dir.parent / "audio"
    out_dir = Path(args.out_dir) if args.out_dir else scenario.with_suffix("").parent / "out"
    out_path = out_dir / f"{scenario.stem}.mp4"

    voice = cfg.voice_en if cfg.language == "en" else cfg.voice_ru
    log.info("Synthesising %d segments with voice %s ...", len(segments), voice)
    for i, seg in enumerate(segments):
        out = audio_dir / f"seg_{i:03d}.wav"
        if out.exists():
            log.debug("reusing %s", out)
            continue
        result = tts_local.synthesize(seg.voice, voice, audio_dir, cfg.language)
        if result is None:
            print(f"❌ TTS failed on segment {i + 1}", file=sys.stderr)
            return 1
        # Normalise filename for assembler
        if result.name != out.name:
            result.rename(out)

    music = cfg.music_path if Path(cfg.music_path).is_file() else None
    log.info("Assembling MP4 (music: %s) ...", music or "none")
    final = assemble_documentary(
        segments,
        image_dir=image_dir,
        audio_dir=audio_dir,
        out_path=out_path,
        music_path=music,
        burn_subtitles=cfg.burn_subtitles,
        music_volume=cfg.music_volume,
        crossfade=cfg.crossfade,
    )
    if final is None:
        print("❌ assembly failed", file=sys.stderr)
        return 1

    print(f"✅ documentary: {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
