#!/usr/bin/env python3
"""Generate AI documentary images from a markdown scenario.

Tries to run Stable Diffusion locally. If it cannot (no GPU / no diffusers),
prints instructions for the Colab notebook instead.

Usage:
    python scripts/generate_images.py docs/scenarios/machiavelli_001.md \
        --out-dir data/ai_doc/machiavelli_001/images
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from shorts_clipper.ai_doc.scenario import load_scenario  # noqa: E402

log = logging.getLogger(__name__)


def _try_local_sd():
    try:
        import diffusers  # noqa: F401
        import torch  # noqa: F401

        return True
    except Exception:
        return False


def _generate_local(
    scenario, out_dir, model_id, style_suffix, seed, width, height, steps, guidance
):
    import torch
    from diffusers import StableDiffusionPipeline

    pipe = StableDiffusionPipeline.from_pretrained(
        model_id,
        torch_dtype=torch.float16,
        safety_checker=None,
        requires_safety_checker=False,
    )
    if torch.cuda.is_available():
        pipe = pipe.to("cuda")
        pipe.enable_attention_slicing()
    else:
        pipe = pipe.to("cpu")
        pipe.enable_model_cpu_offload()

    generator = torch.Generator(device="cuda" if torch.cuda.is_available() else "cpu").manual_seed(
        seed
    )
    for i, seg in enumerate(scenario[1]):
        if not seg.prompt:
            print(f"  [{i + 1}] skip (no prompt)")
            continue
        out_path = out_dir / f"seg_{i:03d}.png"
        if out_path.exists():
            print(f"  [{i + 1}/{len(scenario[1])}] skip (exists): {out_path}")
            continue
        prompt = seg.prompt + ", " + style_suffix
        print(f"  [{i + 1}/{len(scenario[1])}] generating: {seg.title}")
        image = pipe(
            prompt=prompt,
            negative_prompt="text, watermark, signature, low quality, blurry, deformed",
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=guidance,
            generator=generator,
        ).images[0]
        image.save(out_path)
        print(f"    saved: {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="Markdown scenario file")
    parser.add_argument("--out-dir", required=True, help="Output image directory")
    parser.add_argument("--model", default="runwayml/stable-diffusion-v1-5")
    parser.add_argument(
        "--style",
        default="old master oil painting, dark moody chiaroscuro, cinematic composition, umber and gold palette",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--guidance", type=float, default=7.5)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    scenario_path = Path(args.scenario)
    if not scenario_path.is_file():
        print(f"❌ scenario not found: {scenario_path}", file=__import__("sys").stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    meta, segments = load_scenario(scenario_path)
    log.info("Loaded %d segments", len(segments))

    if not _try_local_sd():
        print("\n❌ Stable Diffusion (diffusers) not installed.")
        print("   Install: pip install diffusers transformers accelerate torch")
        print("   Or use the Colab notebook: notebooks/generate_images.ipynb")
        print("   Upload the scenario there, run all cells, download images.zip.")
        return 1

    _generate_local(
        (meta, segments),
        out_dir,
        args.model,
        args.style,
        args.seed,
        args.width,
        args.height,
        args.steps,
        args.guidance,
    )
    print(f"\n✅ Done: {len(segments)} images in {out_dir}")
    return 0


if __name__ == "__main__":
    import logging

    raise SystemExit(main())
