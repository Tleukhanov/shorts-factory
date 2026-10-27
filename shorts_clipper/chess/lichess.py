"""Lichess API helpers for tournament and team ingestion.

Real-game analysis needs real games.  Lichess exposes tournament metadata,
tournament games as a stream of PGNs, and team rosters as NDJSON.  Everything
is cached under ``data/lichess/`` so a normal run only touches the network
once.  A small module-level semaphore keeps concurrent requests to at most
two, and a polite delay is inserted between separate calls.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

import requests

from shorts_clipper.chess import analysis

log = logging.getLogger(__name__)

BASE = "https://lichess.org"
DEFAULT_CACHE_DIR = "data/lichess"
DEFAULT_DELAY = 0.35
_CONCURRENT = threading.Semaphore(2)


class LichessError(Exception):
    """Something went wrong fetching from Lichess."""


class _FakeResponse:
    """A tiny requests.Response stand-in for cache hits.

    Cache hits do not need status codes or streaming, but the callers expect
    a ``.text`` attribute and a context manager.
    """

    def __init__(self, text: str):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _parse_tournament_id(url_or_id: str) -> str:
    """Turn a Lichess tournament URL or a bare id into the id.

    Accepts ``https://lichess.org/tournament/MwiQDf4S`` or ``MwiQDf4S``.
    Anything that does not look like a Lichess tournament id is returned as-is
    so the caller gets the real 404 from the API rather than a made-up error.
    """
    text = (url_or_id or "").strip()
    if not text:
        return ""
    match = re.search(r"/tournament/([a-zA-Z0-9]+)", text)
    if match:
        return match.group(1)
    return text


def _cache_dir(path: str | Path | None = None) -> Path:
    target = Path(path or DEFAULT_CACHE_DIR)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _cached(name: str, cache_dir: str | Path | None) -> Path:
    return _cache_dir(cache_dir) / name


def _use_cache(path: Path) -> _FakeResponse | None:
    """Return a fake response if *path* exists and is non-empty."""
    if path.is_file() and path.stat().st_size > 0:
        log.debug("using cached %s", path)
        return _FakeResponse(path.read_text(encoding="utf-8", errors="replace"))
    return None


def _get(
    url: str,
    cache_path: Path,
    headers: dict[str, str] | None = None,
    stream: bool = False,
    timeout: int = 120,
) -> requests.Response | _FakeResponse:
    """GET *url*, respecting cache and the global concurrency limit.

    Returns a response-like object with a ``.text`` attribute and a context
    manager.  Network responses are written to *cache_path* when streaming is
    False so the next run can read the cache.
    """
    cached = _use_cache(cache_path)
    if cached is not None:
        return cached

    with _CONCURRENT:
        log.info("fetching %s", url)
        resp = requests.get(
            url,
            headers=headers,
            stream=stream,
            timeout=timeout,
        )
        resp.raise_for_status()
        if stream:
            return resp

        text = resp.text
        cache_path.write_text(text, encoding="utf-8")
        time.sleep(DEFAULT_DELAY)
        return _FakeResponse(text)


def fetch_tournament(
    tournament_id: str,
    *,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Fetch tournament metadata.

    ``https://lichess.org/api/tournament/{id}`` returns JSON.  The result is
    cached as ``{id}.json`` under *cache_dir*.
    """
    tournament_id = _parse_tournament_id(tournament_id)
    url = f"{BASE}/api/tournament/{tournament_id}"
    cache_path = _cached(f"{tournament_id}.json", cache_dir)
    with _get(url, cache_path) as resp:
        try:
            return json.loads(resp.text)
        except json.JSONDecodeError as exc:
            raise LichessError(f"invalid tournament JSON for {tournament_id}") from exc


def fetch_tournament_games(
    tournament_id: str,
    *,
    cache_dir: str | Path | None = None,
) -> list[object]:
    """Fetch tournament games as parsed python-chess game objects.

    ``https://lichess.org/api/tournament/{id}/games`` returns newline-delimited
    PGNs separated by blank lines.  The raw stream is cached as
    ``{id}_games.pgn`` and then parsed into games.

    Returns an empty list when python-chess is unavailable or the response
    contains no parseable games.
    """
    tournament_id = _parse_tournament_id(tournament_id)
    url = f"{BASE}/api/tournament/{tournament_id}/games"
    cache_path = _cached(f"{tournament_id}_games.pgn", cache_dir)
    cached = _use_cache(cache_path)

    if cached is not None:
        return parse_games(cached.text)

    with _CONCURRENT:
        log.info("fetching tournament games from %s", url)
        with requests.get(url, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            cache_path.write_bytes(resp.content)
        time.sleep(DEFAULT_DELAY)

    return parse_games(cache_path.read_text(encoding="utf-8", errors="replace"))


def parse_games(text: str) -> list[object]:
    """Parse a concatenated PGN blob into python-chess game objects."""
    chess = analysis._chess_module()  # noqa: SLF001
    if chess is None:
        log.warning("python-chess is not installed, cannot parse tournament games")
        return []

    import io

    games: list[object] = []
    handle = io.StringIO(text)
    while True:
        try:
            game = chess.pgn.read_game(handle)
        except Exception:
            log.debug("PGN parse failed", exc_info=True)
            break
        if game is None:
            break
        if any(True for _ in game.mainline_moves()):
            games.append(game)
    return games


# Backwards-compatible alias kept for internal callers.
_parse_pgn_text = parse_games


def fetch_team_members(
    team_id: str,
    *,
    cache_dir: str | Path | None = None,
) -> list[str]:
    """Fetch the user names in a Lichess team.

    ``https://lichess.org/api/team/{team_id}/users`` returns NDJSON.  Each
    non-empty line is a user object; we keep the ``name`` field.
    """
    team_id = (team_id or "").strip()
    if not team_id:
        return []
    url = f"{BASE}/api/team/{team_id}/users"
    cache_path = _cached(f"{team_id}_members.json", cache_dir)
    cached = _use_cache(cache_path)
    if cached is not None:
        return _parse_ndjson_names(cached.text)

    with _CONCURRENT:
        log.info("fetching team members from %s", url)
        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        cache_path.write_bytes(resp.content)
        time.sleep(DEFAULT_DELAY)
        return _parse_ndjson_names(resp.text)


def _parse_ndjson_names(text: str) -> list[str]:
    names: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = obj.get("username") or obj.get("name") or obj.get("id")
        if name:
            names.append(str(name).lower())
    return names


def game_url(game: object) -> str:
    """Best-effort game URL from PGN headers."""
    headers = dict(getattr(game, "headers", {}) or {})
    for key in ("Site", "LichessURL", "URL"):
        value = headers.get(key)
        if value and isinstance(value, str):
            return value.strip()
    return ""
