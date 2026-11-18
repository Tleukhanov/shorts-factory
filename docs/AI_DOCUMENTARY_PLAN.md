# AI Documentary Pipeline — implementation plan (Variant 1: 100% free)

## Goal

Build a fully free, local-first content pipeline for long-form AI documentaries:

- **Script** — Copilot / ChatGPT free (markdown)
- **Images** — Stable Diffusion in Colab/Kaggle (T4 GPU, free)
- **Voice** — local TTS (Kokoro for EN, Silero for RU)
- **Assembly** — shorts-factory (FFmpeg, Ken Burns, crossfade, music, subs)

No paid APIs. Everything runs on free tools or local CPU.

## Models downloaded (local)

| Model | Size | Path | Purpose |
|---|---:|---|---|
| Kokoro-82M | ~320 MB | HuggingFace cache (`hexgrad/Kokoro-82M`) | English TTS, 8 voices, high quality |
| Silero TTS ru_v3 | 56.5 MB | `~/.cache/torch/hub/snakers4_silero-models_master` | Russian TTS, 5 voices (aidar, baya, kseniya, xenia) |
| en_core_web_sm | 12 MB | site-packages | Kokoro phonemizer dependency |

**Important:** Kokoro supports EN/ES/FR/HI/IT/PT/JA/ZH but **not Russian**. For Russian text use Silero (or Piper). The plan therefore uses:

- Russian documentaries → Silero voices (`baya` — calm female, `aidar` — male)
- English documentaries → Kokoro voices (`af_heart` — calm female, `am_adam` — male)

## Architecture

```
docs/AI_DOCUMENTARY_PLAN.md        (this file)
scripts/generate_images.py          # Colab/Kaggle notebook + local wrapper
shorts_clipper/audio/tts_local.py   # Kokoro + Silero wrapper
shorts_clipper/ai_doc/              # new package
  __init__.py
  config.py                         # Config, from_file, defaults
  scenario.py                       # markdown scenario parser → segments
  images.py                         # image generation (SD via Colab/Kaggle or local)
  voice.py                          # TTS per segment (Kokoro/Silero)
  assemble.py                       # Ken Burns + crossfade + music + subs → MP4
  cli.py                            # "shorts-clipper ai-doc ..." command
config/ai_documentary.json          # default config
tests/test_ai_doc_*.py              # tests
```

## Step-by-step

### Phase 1 — Scenario parser

- Markdown format with `## Segment N (start - end)` headings.
- Each segment: `Image:` prompt, `Voice:` text, `Music:` mood, `Subtitle:` text.
- Output: `list[Segment]` with `duration`, `prompt`, `voice_text`, `music_mood`.
- Validate: no missing fields, durations sum, total duration 5–45 min.

### Phase 2 — Image generation (Colab/Kaggle)

- Colab/Kaggle notebook `generate_images.ipynb`:
  - load Stable Diffusion model (e.g. `runwayml/stable-diffusion-v1-5` or SDXL)
  - read scenario prompts, generate images under `data/ai_doc/<project>/images/`
  - consistent style via fixed seed + base prompt suffix
  - download images to local repo
- Local wrapper can call the notebook via Kaggle API, or use local SD if GPU available.
- Cache: skip images that already exist.

### Phase 3 — Voice generation

- `shorts_clipper/audio/tts_local.py`:
  - `synthesize_en(text, voice)` — Kokoro (`af_heart`, `am_adam`, …)
  - `synthesize_ru(text, voice)` — Silero (`baya`, `aidar`, …)
  - return WAV path; deterministic per segment (cache by text hash)
- Merge per-segment WAVs into a single voice track with exact timings.

### Phase 4 — Assembly

- For each segment image:
  - Ken Burns zoom/pan (random but seeded direction)
  - duration = segment duration
- Crossfade between segments (e.g. 0.8s)
- Mix background music (royalty-free from `data/music/`)
- Burn subtitles from `Subtitle:` field
- Output: MP4 1080p 30fps, 6–40 min

Reuse existing modules:
- `shorts_clipper/visual/` — Ken Burns
- `shorts_clipper/captions/generator.py` — ASS subtitles
- `shorts_clipper/captions/music.py` — music bed
- `shorts_clipper/chess/clip.py` — ffmpeg concat patterns
- `shorts_clipper/chess/tactics.py` — `_build_voice_track` (audio mixing)

### Phase 5 — Shorts cuts

- From the long documentary, cut 15–35s vertical clips from the most emotional segments.
- Add hook text + CTA.
- Export to `outputs/ai_doc/shorts/`.

## Config (`config/ai_documentary.json`)

```json
{
  "language": "ru",
  "ru_voice": "baya",
  "en_voice": "af_heart",
  "image_model": "runwayml/stable-diffusion-v1-5",
  "image_style": "painterly, cinematic lighting, dark moody atmosphere",
  "segment_default_seconds": 30,
  "crossfade_seconds": 0.8,
  "music_volume": 0.18,
  "output_width": 1080,
  "output_height": 1920,
  "fps": 30
}
```

## CLI

```bash
shorts-clipper ai-doc --project machiavelli \
  --scenario docs/scenarios/machiavelli.md \
  --images data/ai_doc/machiavelli/images/

shorts-clipper ai-doc --project machiavelli --shorts-only
```

## Limitations / notes

- Kokoro: no Russian → use Silero for RU.
- Silero voices sound less natural than Kokoro but are free/local.
- SD image generation in Colab: 30h/week, 12h session limit.
- Long documentaries need many images (30–40 min ≈ 60–80 segments → 60–80 images).
- Music must be royalty-free.
- Storage: ~100 MB per project.

## Success criteria (MVP)

- One 30-min Russian documentary assembled from markdown + SD images + Silero voice
- One 15-min English documentary with Kokoro voice
- 3–5 Shorts cuts from each
- All produced with $0 cost (models local / free GPU)
