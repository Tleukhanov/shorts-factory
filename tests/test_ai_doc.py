"""Tests for the AI documentary scenario parser."""

from __future__ import annotations

import pytest

from shorts_clipper.ai_doc.config import AiDocumentaryConfig
from shorts_clipper.ai_doc.scenario import load_scenario, parse_markdown_scenario

SAMPLE = """
---
title: Test Doc
---

## Segment 1 — First Step
image: a.jpg
voice: Power is not loud.
subtitle: Power quiet.

## Segment 2 — Second Step
image: b.jpg
voice: Be the frame, not the painting.
subtitle: Be the frame.
"""


def test_parse_markdown_scenario():
    meta, segments = parse_markdown_scenario(SAMPLE)
    assert meta["title"] == "Test Doc"
    assert len(segments) == 2
    assert segments[0].image == "a.jpg"
    assert segments[0].voice == "Power is not loud."
    assert segments[0].subtitle == "Power quiet."
    assert segments[1].title == "Second Step"


def test_load_scenario_roundtrip(tmp_path):
    p = tmp_path / "x.md"
    p.write_text(SAMPLE, encoding="utf-8")
    meta, segments = load_scenario(p)
    assert meta["title"] == "Test Doc"
    assert len(segments) == 2


def test_parse_rejects_empty_scenario():
    with pytest.raises(ValueError):
        parse_markdown_scenario("no headings here")


def test_config_defaults():
    cfg = AiDocumentaryConfig()
    assert cfg.language == "en"
    assert cfg.voice_en == "bm_george"
    assert cfg.burn_subtitles is True
