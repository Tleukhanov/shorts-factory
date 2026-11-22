# AI Documentary — Format & Clipping Guide

## Concept

Long-form AI documentaries (15–40 min) built from:
- **AI-generated paintings** (Stable Diffusion, consistent style)
- **Ken Burns transitions** (zoom/pan between images)
- **Local TTS voiceover** (Kokoro EN / Silero RU)
- **Background music** (tense, ambient, royalty-free)
- **Burned-in subtitles** (ASS, one line per segment)

Shorts/Reels/TikTok are **cut from key moments** of the long video.

## Video structure

```
[0:00 - 0:15]  Hook: strong visual + provocative claim
[0:15 - X:XX]  Body: segments with images + voice + subtitles
[X:XX - end]   Outro: summary + CTA (subscribe, Telegram, next video)
```

Each segment = one scene:
- 1 AI image (16:9, 1024×576 or 1920×1080)
- 1 voiceover line (10–45 sec)
- 1 subtitle line
- Ken Burns zoom/pan (random direction, seeded)
- crossfade transition (0.8s) between segments

## Music selection

### Available tracks (data/music/)

| Track | Mood | BPM | Use case |
|---|---|---:|---|
| `dark_industrial_loop.wav` | Aggressive, driving | 134 | Not for documentary |
| `tense_ambient.wav` | Tense, cynical, ambient | 68 | Documentary, philosophy, strategy |
| `generated_phonk_loop.wav` | Phonk, energetic | 132 | Shorts, drama, challenges |

### How music is selected

1. Config `music_path` points to a track.
2. If the file doesn't exist, `resolve_music()` tries:
   - explicit `--music` flag
   - `cfg.music_path`
   - first `*.wav/*.mp3/*.m4a/*.ogg` in `data/music/`
   - procedural fallback (tense ambient generator)
3. Music is mixed with EQ (cuts 2–4 kHz where voice sits) and ducked to `music_volume` (default 0.20).
4. If `--no-music` is set, renders without bed.

### Music guidelines

- **Documentary (long-form):** tense ambient, 60–80 BPM, volume 0.15–0.25, EQ on.
- **Motivation:** calm ambient, 60–70 BPM, volume 0.10–0.15.
- **Drama/shorts:** phonk, 130–140 BPM, volume 0.08–0.12, beat-synced.
- **Stories:** soft ambient, volume 0.08–0.12.

## Clipping guide

### From long video to Shorts

1. Identify key moments (emotional peaks, revelations, quotes).
2. Cut 15–35s vertical clips (9:16, 1080×1920).
3. Add hook text + CTA.
4. Use the same music track (or a shorter cut).
5. Export to `outputs/ai_doc/shorts/`.

### Clipping workflow

```bash
# Generate full documentary
python scripts/make_ai_documentary.py docs/scenarios/machiavelli_001.md \
  --image-dir data/ai_doc/machiavelli_001/images \
  --out-dir data/ai_doc/machiavelli_001/out

# Cut Shorts from key moments (manual or via ffmpeg)
ffmpeg -ss 00:00:30 -i output.mp4 -t 25 -vf "crop=1080:1920:420:0,scale=1080:1920" short_01.mp4
```

### Shorts structure

```
[0:00-0:03] Hook: provocative quote or question
[0:03-0:20] Body: 2-3 key sentences
[0:20-0:25] CTA: subscribe / next video
```

## Scene template

```markdown
## Segment N — Title
prompt: <SD prompt for this scene>
voice: "Voiceover text for this scene."
subtitle: On-screen subtitle text.
music: (optional) track name or mood
```

## Image consistency rules

1. **One style suffix** for all prompts: `old master oil painting, dark moody chiaroscuro, cinematic composition, umber and gold palette`
2. **One seed** per project (e.g., `seed=42`)
3. **One checkpoint** (e.g., `runwayml/stable-diffusion-v1-5` or SDXL)
4. **Width 1024, height 576** (16:9) for long-form, or **1080×1920** for Shorts
5. **Steps 30, guidance 7.5** — good balance of quality and speed
6. **Negative prompt:** `text, watermark, signature, low quality, blurry, deformed`

## Production workflow

```
1. Write scenario in markdown (Copilot / ChatGPT free)
2. Generate images (Colab/Kaggle SD or local)
3. Generate TTS (Kokoro/Silero, local)
4. Assemble MP4 (shorts-factory)
5. Export + cut Shorts
6. Publish to YouTube (long + Shorts) + Reels + TikTok
```

## KPI for long-form

- **Retention > 40%** on 30-min video = excellent
- **CTR > 4%** on thumbnail
- **Avg view duration > 8 min** = good
- **Comments** = key algorithm signal
- **Subscribers** from each video

## Content ideas

### 1. Machiavelli's The Prince (30-40 min)
- 30-40 AI paintings of renaissance, war, power
- Voice reads key passages + commentary
- Ambient/dark music, subtitles

### 2. Stoicism (15-25 min)
- Quotes from Marcus Aurelius, Seneca, Epictetus
- AI paintings in classical style
- Contemplative voice + calm music

### 3. History documentaries (15-25 min)
- Historical events, figures, battles
- AI paintings in historical style
- Narration + music + subtitles

### 4. Philosophy (20-30 min)
- Existentialism, Eastern philosophy, etc.
- AI paintings in painterly style
- Contemplative voice + ambient music

## Next steps

1. Generate images via Colab notebook
2. Test assembly with crossfade (xfade in filter_complex)
3. Write full 20-30 min scenario
4. Cut Shorts from key moments
5. Publish and measure retention
