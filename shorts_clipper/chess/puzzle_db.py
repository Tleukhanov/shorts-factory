"""Lichess puzzle database: download, filter and select human-tested tactics.

The puzzle DB is the antidote to "Stockfish-boring" positions.  Every entry
was played, solved and rated by humans on Lichess, so it carries real evidence
of whether the position is interesting.  We stream-decompress the zstd file
instead of unpacking the ~1.5 GB CSV, and cache the filtered selection so
normal runs do not touch the 300 MB download again.

Schema (https://database.lichess.org/):
    PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,
    GameUrl,OpeningTags,DailyDate

Moves[0] is the opponent's setup move; Moves[1:] is the solution line.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import heapq
import json
import logging
import math
from pathlib import Path
from typing import ClassVar

import requests
import zstandard

log = logging.getLogger(__name__)

DB_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"

# Phase/theme markers that are not interesting on their own.
_BORING_ONLY_THEMES = frozenset({"crushing", "advantage", "equality"})
# Themes that make a puzzle feel like a computer exercise rather than a tactic.
_REJECT_THEMES = frozenset({"mateIn1", "oneMove", "veryLong", "hangingPiece"})
# Interesting tactical motifs.  A puzzle must carry at least one of these.
_ALLOWED_THEMES = frozenset(
    {
        "fork",
        "pin",
        "skewer",
        "discoveredAttack",
        "doubleCheck",
        "deflection",
        "attraction",
        "clearance",
        "interference",
        "intermezzo",
        "xRayAttack",
        "zugzwang",
        "trappedPiece",
        "capturingDefender",
        "sacrifice",
        "quietMove",
        "mateIn2",
        "mateIn3",
        "mateIn4",
        "mateIn5",
        "backRankMate",
        "smotheredMate",
        "anastasiaMate",
        "arabianMate",
        "bodenMate",
        "doubleBishopMate",
        "dovetailMate",
        "hookMate",
        "killBoxMate",
        "vukovicMate",
    }
)
# Themes that get a small selection bonus because viewers love them.
_PREFERRED_THEMES = frozenset(
    {
        "sacrifice",
        "quietMove",
        "discoveredAttack",
        "smotheredMate",
        "backRankMate",
        "zugzwang",
        "deflection",
        "attraction",
    }
)


@dataclasses.dataclass(frozen=True)
class Puzzle:
    """One Lichess puzzle."""

    id: str
    fen: str
    moves: tuple[str, ...]
    rating: int
    rating_deviation: int
    popularity: int
    nb_plays: int
    themes: frozenset[str]
    game_url: str
    opening_tags: tuple[str, ...]
    daily_date: str | None

    # Human-readable motif names in Russian.  Keep short so they fit the band.
    _THEME_LABELS: ClassVar[dict[str, str]] = {
        "fork": "вилка",
        "pin": "связка",
        "skewer": "сквозной удар",
        "discoveredAttack": "вскрытое нападение",
        "doubleCheck": "двойной шах",
        "deflection": "отвлечение",
        "attraction": "завлечение",
        "clearance": "освобождение линии",
        "interference": "перекрытие",
        "intermezzo": "промежуточный удар",
        "xRayAttack": "рентген",
        "zugzwang": "цугцванг",
        "trappedPiece": "ловушка фигуры",
        "capturingDefender": "уничтожение защитника",
        "sacrifice": "жертва",
        "quietMove": "тихий ход",
        "mateIn2": "мат в 2 хода",
        "mateIn3": "мат в 3 хода",
        "mateIn4": "мат в 4 хода",
        "mateIn5": "мат в 5 ходов",
        "backRankMate": "мат по последней линии",
        "smotheredMate": "спёртый мат",
        "anastasiaMate": "мат Анастасии",
        "arabianMate": "аравский мат",
        "bodenMate": "мат Бодена",
        "doubleBishopMate": "мат двумя слонами",
        "dovetailMate": "мат в лоб",
        "hookMate": "мат крючком",
        "killBoxMate": "мат в коробке",
        "vukovicMate": "мат Вуковича",
    }

    @property
    def setup_move(self) -> str:
        return self.moves[0]

    @property
    def solution_moves(self) -> tuple[str, ...]:
        return self.moves[1:]

    def puzzle_fen(self) -> str | None:
        """FEN after the opponent's setup move."""
        try:
            import chess

            board = chess.Board(self.fen)
            board.push(chess.Move.from_uci(self.setup_move))
            return board.fen()
        except Exception:
            log.debug("could not build puzzle FEN for %s", self.id, exc_info=True)
            return None

    def solver_color(self) -> str | None:
        try:
            import chess

            board = chess.Board(self.fen)
            board.push(chess.Move.from_uci(self.setup_move))
            return "white" if board.turn == chess.WHITE else "black"
        except Exception:
            return None

    def primary_theme(self) -> str:
        """Best theme for grouping/diversity."""
        for theme in _PREFERRED_THEMES:
            if theme in self.themes:
                return theme
        for theme in _ALLOWED_THEMES:
            if theme in self.themes:
                return theme
        # Fallback: any theme at all (should not happen after filtering).
        return sorted(self.themes)[0] if self.themes else "unknown"

    def theme_label(self) -> str:
        """Russian label for the primary theme."""
        return self._THEME_LABELS.get(self.primary_theme(), self.primary_theme())

    def solution_length(self) -> int:
        """Number of solver moves (not total half-moves)."""
        return math.ceil(len(self.solution_moves) / 2)


@dataclasses.dataclass
class TacticsConfig:
    """Quality gate configuration."""

    db_url: str = DB_URL
    db_path: str | Path = "data/puzzles/lichess_db_puzzle.csv.zst"
    cache_path: str | Path = "data/puzzles/selected.json"
    rating_min: int = 1400
    rating_max: int = 2000
    rating_deviation_max: int = 100
    popularity_min: int = 85
    plays_min: int = 2000
    max_solution_moves: int = 4
    allow_themes: frozenset[str] = dataclasses.field(default_factory=lambda: _ALLOWED_THEMES)
    reject_themes: frozenset[str] = dataclasses.field(default_factory=lambda: _REJECT_THEMES)
    boring_themes: frozenset[str] = dataclasses.field(default_factory=lambda: _BORING_ONLY_THEMES)
    preferred_themes: frozenset[str] = dataclasses.field(default_factory=lambda: _PREFERRED_THEMES)
    require_allowed_theme: bool = True
    reject_if_only_boring: bool = True
    target_rating: int = 1700
    max_per_theme: int = 1
    seed: int = 42
    # Publishing metadata.
    club_name: str = "Senpai"
    lichess_team_url: str = "https://lichess.org/team/senpai"
    whatsapp_url: str = ""
    hashtags: tuple[str, ...] = ("#шахматы", "#тактика", "#shorts")

    def cache_key(self) -> str:
        """Stable hash used to invalidate the cached selection."""
        payload = {
            "rating_min": self.rating_min,
            "rating_max": self.rating_max,
            "rating_deviation_max": self.rating_deviation_max,
            "popularity_min": self.popularity_min,
            "plays_min": self.plays_min,
            "max_solution_moves": self.max_solution_moves,
            "allow": sorted(self.allow_themes),
            "reject": sorted(self.reject_themes),
            "boring": sorted(self.boring_themes),
            "preferred": sorted(self.preferred_themes),
            "require_allowed": self.require_allowed_theme,
            "reject_only_boring": self.reject_if_only_boring,
            "target": self.target_rating,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    @classmethod
    def from_file(cls, path: str | Path) -> TacticsConfig:
        path = Path(path)
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Convert list-of-strings to frozensets for the theme fields.
        for key in ("allow_themes", "reject_themes", "boring_themes", "preferred_themes"):
            if key in raw and isinstance(raw[key], list):
                raw[key] = frozenset(raw[key])
        # Convert hashtags list to tuple.
        if "hashtags" in raw and isinstance(raw["hashtags"], list):
            raw["hashtags"] = tuple(raw["hashtags"])
        # Resolve Path strings.
        for key in ("db_path", "cache_path"):
            if key in raw:
                raw[key] = Path(raw[key])
        return cls(**raw)


def _parse_puzzle(row: dict[str, str]) -> Puzzle | None:
    try:
        moves = tuple(row["Moves"].strip().split())
        if len(moves) < 2:
            return None
        return Puzzle(
            id=row["PuzzleId"],
            fen=row["FEN"],
            moves=moves,
            rating=int(row["Rating"]),
            rating_deviation=int(row["RatingDeviation"]),
            popularity=int(row["Popularity"]),
            nb_plays=int(row["NbPlays"]),
            themes=frozenset(row["Themes"].strip().split()),
            game_url=row["GameUrl"],
            opening_tags=tuple(row.get("OpeningTags", "").strip().split() or ()),
            daily_date=row.get("DailyDate") or None,
        )
    except Exception:
        log.debug("could not parse puzzle row: %s", row, exc_info=True)
        return None


def iter_puzzles(path: str | Path):
    """Yield :class:`Puzzle` objects by streaming the zstd CSV."""
    import io

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"puzzle DB not found: {path}")
    with path.open("rb") as fh:
        dctx = zstandard.ZstdDecompressor()
        reader = dctx.stream_reader(fh)
        text = io.TextIOWrapper(reader, encoding="utf-8", newline="")
        for row in csv.DictReader(text):
            puzzle = _parse_puzzle(row)
            if puzzle is not None:
                yield puzzle


def download_db(url: str = DB_URL, dest: str | Path | None = None) -> Path:
    """Download the Lichess puzzle DB if it does not already exist.

    Returns the local path.  Does nothing if *dest* already exists and is
    non-empty unless the caller removes it first.
    """
    dest = Path(dest or "data/puzzles/lichess_db_puzzle.csv.zst")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        log.info("puzzle DB already exists at %s", dest)
        return dest

    log.info("downloading Lichess puzzle DB from %s", url)
    with requests.get(url, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 1024 * 1024
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                fh.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    log.info("downloaded %d%% (%d MB / %d MB)", pct, downloaded // (1024 * 1024), total // (1024 * 1024))
    log.info("puzzle DB saved to %s", dest)
    return dest


def _passes_quality(puzzle: Puzzle, cfg: TacticsConfig) -> bool:
    if not (cfg.rating_min <= puzzle.rating <= cfg.rating_max):
        return False
    if puzzle.rating_deviation > cfg.rating_deviation_max:
        return False
    if puzzle.popularity < cfg.popularity_min:
        return False
    if puzzle.nb_plays < cfg.plays_min:
        return False
    if puzzle.solution_length() > cfg.max_solution_moves:
        return False
    if puzzle.themes & cfg.reject_themes:
        return False
    if cfg.reject_if_only_boring and puzzle.themes <= cfg.boring_themes:
        return False
    if cfg.require_allowed_theme and not (puzzle.themes & cfg.allow_themes):
        return False
    return True


def _score(puzzle: Puzzle, cfg: TacticsConfig) -> float:
    """Higher is better.  Deterministic except the tiny random tie-break."""
    score = puzzle.popularity * 2.0
    score += min(math.log2(max(puzzle.nb_plays, 1)), 14.0) * 5.0
    if puzzle.themes & cfg.preferred_themes:
        score += 15.0
    if puzzle.daily_date:
        score += 10.0
    score -= abs(puzzle.rating - cfg.target_rating) / 50.0
    return score


def _load_cached_selection(path: Path, key: str) -> list[Puzzle] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("key") != key:
            return None
        return [_puzzle_from_dict(item) for item in raw.get("puzzles", [])]
    except Exception:
        log.debug("could not load cached puzzle selection", exc_info=True)
        return None


def _save_cached_selection(path: Path, key: str, puzzles: list[Puzzle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "key": key,
        "count": len(puzzles),
        "puzzles": [_puzzle_to_dict(p) for p in puzzles],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _puzzle_to_dict(p: Puzzle) -> dict:
    return {
        "id": p.id,
        "fen": p.fen,
        "moves": list(p.moves),
        "rating": p.rating,
        "rating_deviation": p.rating_deviation,
        "popularity": p.popularity,
        "nb_plays": p.nb_plays,
        "themes": sorted(p.themes),
        "game_url": p.game_url,
        "opening_tags": list(p.opening_tags),
        "daily_date": p.daily_date,
    }


def _puzzle_from_dict(d: dict) -> Puzzle:
    return Puzzle(
        id=d["id"],
        fen=d["fen"],
        moves=tuple(d["moves"]),
        rating=d["rating"],
        rating_deviation=d["rating_deviation"],
        popularity=d["popularity"],
        nb_plays=d["nb_plays"],
        themes=frozenset(d["themes"]),
        game_url=d["game_url"],
        opening_tags=tuple(d.get("opening_tags", [])),
        daily_date=d.get("daily_date") or None,
    )


class _TopK:
    """Min-heap keeping the highest-scoring *k* puzzles seen so far."""

    def __init__(self, k: int):
        self.k = k
        self._heap: list[tuple[float, int, Puzzle]] = []
        self._counter = 0

    def push(self, score: float, puzzle: Puzzle) -> None:
        self._counter += 1
        entry = (score, self._counter, puzzle)
        if len(self._heap) < self.k:
            heapq.heappush(self._heap, entry)
        elif score > self._heap[0][0]:
            heapq.heapreplace(self._heap, entry)

    def items(self) -> list[Puzzle]:
        """Return items sorted by score descending."""
        return [p for _, _, p in sorted(self._heap, key=lambda x: x[0], reverse=True)]

    def __len__(self) -> int:
        return len(self._heap)


def _load_used(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")).get("ids", []))
    except Exception:
        log.debug("could not load used puzzle IDs", exc_info=True)
        return set()


def _save_used(path: Path, ids: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ids": sorted(ids)}, ensure_ascii=False, indent=2), encoding="utf-8")


def select_puzzles(
    db_path: str | Path,
    count: int = 5,
    cfg: TacticsConfig | None = None,
    used: set[str] | None = None,
) -> list[Puzzle]:
    """Return *count* high-quality, diverse puzzles from the DB.

    Uses a cached selection when the config matches.  The cache is written to
    *cfg.cache_path*.  Puzzles whose IDs are in *used* are skipped.
    """
    cfg = cfg or TacticsConfig()
    cache_path = Path(cfg.cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    key = cfg.cache_key()
    used = used or set()

    cached = _load_cached_selection(cache_path, key)
    if cached is not None:
        log.info("using cached puzzle selection: %d puzzles", len(cached))
        filtered = [p for p in cached if p.id not in used]
        return _diversify(filtered, count, cfg)

    log.info("scanning puzzle DB for quality tactics...")
    topk = _TopK(max(count * 100, 500))
    scanned = 0
    passed = 0
    for puzzle in iter_puzzles(db_path):
        scanned += 1
        if not _passes_quality(puzzle, cfg):
            continue
        if puzzle.id in used:
            continue
        passed += 1
        topk.push(_score(puzzle, cfg), puzzle)
        if scanned % 100_000 == 0:
            log.info("scanned %d puzzles, %d passed, topk=%d", scanned, passed, len(topk))
    log.info("scanned %d puzzles, %d passed the quality gate", scanned, passed)

    candidates = topk.items()
    selected = _diversify(candidates, len(candidates), cfg)
    _save_cached_selection(cache_path, key, selected)
    return selected[:count]


def _diversify(puzzles: list[Puzzle], count: int, cfg: TacticsConfig) -> list[Puzzle]:
    """Pick *count* puzzles while capping repeats of the same primary theme."""
    seen_themes: dict[str, int] = {}
    result: list[Puzzle] = []
    # First pass: enforce max_per_theme.
    for p in puzzles:
        if len(result) >= count:
            break
        theme = p.primary_theme()
        if seen_themes.get(theme, 0) >= cfg.max_per_theme:
            continue
        result.append(p)
        seen_themes[theme] = seen_themes.get(theme, 0) + 1
    # If we ran out of diverse themes, relax and fill the rest.
    if len(result) < count:
        for p in puzzles:
            if p in result:
                continue
            if len(result) >= count:
                break
            result.append(p)
    return result
