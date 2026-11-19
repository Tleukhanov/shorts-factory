"""AI documentary pipeline: script → public-domain images → local TTS → MP4."""

from __future__ import annotations

from shorts_clipper.ai_doc.config import AiDocumentaryConfig
from shorts_clipper.ai_doc.scenario import Segment, parse_markdown_scenario

__all__ = ["AiDocumentaryConfig", "Segment", "parse_markdown_scenario"]
