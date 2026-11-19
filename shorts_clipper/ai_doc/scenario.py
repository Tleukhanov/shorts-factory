"""Parser for the markdown documentary scenario format.

Format:
    ---
    title: Power Is Not in Loudness
    credits: Machiavelli, Niccolò — The Prince (trans. Marriott)
    ---

    ## Segment 1 — The Quiet Man
    image: b9bfa94617.jpg        # filename in the image directory
    voice: "Most people mistake power for noise. They think the loudest voice …"
    subtitle: Power is not in loudness.

    ## Segment 2 — Step 1: Become Hard to Replace
    image: b6ec943382.jpg
    voice: "Machiavelli never wrote it as … But read the Prince closely …"
    subtitle: Step 1 — Become indispensable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_FRONT_MATTER = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FIELD = re.compile(r"^(image|voice|subtitle|music)\s*:\s*(.+?)\s*$", re.IGNORECASE)
_HEADING = re.compile(r"^##\s+(?:Segment\s*)?\d*\s*[-—:]?\s*(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Segment:
    title: str
    image: str
    voice: str
    subtitle: str
    music: str | None = None


def parse_markdown_scenario(text: str) -> tuple[dict, list[Segment]]:
    """Return ``(metadata, segments)``. Severe problems raise ``ValueError``."""
    meta: dict = {}
    m = _FRONT_MATTER.match(text)
    body = text
    if m:
        body = text[m.end() :]
        for line in m.group(1).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip().lower()] = value.strip()

    segments: list[Segment] = []
    current: dict[str, str] = {}

    def _flush() -> None:
        if not current:
            return
        image = current.get("image", "").strip()
        voice = current.get("voice", "").strip()
        if not image or not voice:
            log.warning("skipping incomplete segment: %s", current.get("title", "<unnamed>"))
            return
        segments.append(
            Segment(
                title=current.get("title", "").strip(),
                image=image,
                voice=voice,
                subtitle=current.get("subtitle", "").strip(),
                music=current.get("music") or None,
            )
        )

    for raw in body.splitlines():
        line = raw.rstrip()
        h = _HEADING.match(line)
        if h:
            _flush()
            current = {"title": h.group(1).strip()}
            continue
        f = _FIELD.match(line)
        if f:
            key = f.group(1).lower()
            value = f.group(2).strip().strip('"').strip("'")
            current[key] = value
            continue

    _flush()
    if not segments:
        raise ValueError("no segments found in scenario")
    return meta, segments


def load_scenario(path: str | Path) -> tuple[dict, list[Segment]]:
    text = Path(path).read_text(encoding="utf-8")
    return parse_markdown_scenario(text)
