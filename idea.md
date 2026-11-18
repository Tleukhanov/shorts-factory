# AI Documentary Pipeline — 100% Free Variant

## Concept

A fully free, local-first AI documentary pipeline built on top of `shorts-factory`.
No paid APIs, no cloud, no subscriptions. Everything runs on free tools:

- **Script** — Copilot / ChatGPT free tier / local LLM
- **Images** — Stable Diffusion (local or Colab/Kaggle)
- **Voice** — Kokoro TTS (CPU, 82M params)
- **Assembly** — shorts-factory (FFmpeg, Ken Burns, music)
- **Music** — royalty-free (Pixabay, Mixkit, FMA)

## Why this works

The format is: **AI paintings + Ken Burns + TTS voice + ambient music**.

This is exactly what channels like InnerVoicez do — and it gets millions of views
with zero production budget. The secret is not the technology, it's the **script
and the consistency of the style**.

## Pipeline

```
1. Script (markdown) → 2. Images (SD) → 3. TTS (Kokoro) → 4. Assembly (shorts-factory) → 5. Publish
```

### Step 1: Script

Write a markdown file with segments:

```markdown
# Machiavelli: The Prince — Chapter 1

## Segment 1 (0:00 - 0:45)
- Image: dark renaissance palace, prince on throne
- Voice: "Machiavelli wrote the Prince in 1513..."
- Music: ambient drone
- Subtitle: "В 1513 году Макиавелли написал..."

## Segment 2 (0:45 - 1:30)
- Image: battlefield, soldiers, smoke
- Voice: "The first lesson: power is not given..."
- Music: drums fade in
```

**Cost:** $0 (Copilot free / ChatGPT free tier / local LLM)

### Step 2: Images

Generate AI paintings via Stable Diffusion:

- **Local:** RTX 4090, 4-6 min per 512x512 image
- **Colab/Kaggle:** free T4 GPU, 30 hrs/week
- **Prompt template:** consistent style + scene description

**Cost:** $0 (local) or $0 (Colab free)

### Step 3: TTS

Kokoro TTS (82M params, CPU, 1x realtime):

- Quality: 7/10 — natural enough for documentary
- Speed: 1x realtime (30 min audio = 30 min generation)
- Languages: EN, RU (multilingual model)
- Cost: $0

### Step 4: Assembly

shorts-factory pipeline:

- Ken Burns zoom/pan on each image
- Crossfade transitions between scenes
- Music mixing with ducking
- Subtitle burn-in
- Output: MP4 (1080p, 30fps)

**Cost:** $0 (FFmpeg, local)

### Step 5: Publish

- YouTube (long-form, 6-12 min)
- Shorts/Reels/TikTok (15-35 sec cuts from the long video)

**Cost:** $0

## Total cost

| Component | Price |
|---|---:|
| Script | $0 |
| Images (local SD) | $0 |
| TTS (Kokoro) | $0 |
| Assembly (FFmpeg) | $0 |
| Music (royalty-free) | $0 |
| **Total per video** | **$0** |

**Limitations:** 30 hrs GPU/week on Colab/Kaggle, 12-hour session limit, manual process.

## Content ideas

### 1. Machiavelli's The Prince (30-40 min)
- 30-40 AI paintings of renaissance, war, power
- Voice reads key passages + commentary
- Ambient/dark music
- Subtitles in Russian

### 2. Motivation series (15-25 min)
- Quotes from Musashi, Peterson, Fridman, etc.
- AI paintings matching each quote
- Pleasant voice, calm music
- Shorts cuts from key moments

### 3. Philosophy (20-30 min)
- Stoicism, existentialism, Eastern philosophy
- AI paintings in painterly style
- Contemplative voice + ambient music

### 4. History documentaries (15-25 min)
- Historical events, figures, battles
- AI paintings in historical style
- Narration + music + subtitles

## Production workflow

```
1. Write script in markdown (Copilot / ChatGPT free)
2. Generate images (Stable Diffusion in Colab/Kaggle)
3. Generate TTS (Kokoro, local)
4. Assemble (shorts-factory)
5. Export MP4
6. Cut Shorts from key moments
7. Publish to YouTube + Shorts + Reels + TikTok
```

## KPI for long-form AI documentary

- **Retention > 40%** on 30-min video = excellent
- **CTR > 4%** on thumbnail
- **Avg view duration > 8 min** = good
- **Comments** = key algorithm signal
- **Subscribers** from each video

## Next steps

1. Create `ai_documentary.py` module in `shorts-factory`
2. Create scenario template (`scenario.md`)
3. Create image generation script (Colab/Kaggle)
4. Integrate Kokoro TTS
5. Test with one Machiavelli chapter
6. Scale to 10+ videos/month
