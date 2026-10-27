"""CLI entry point for shorts-clipper.

Usage:
    python -m shorts_clipper clip <url> [options]
    python -m shorts_clipper autopilot [options]
    python -m shorts_clipper scout
    python -m shorts_clipper inspect <file.mp4>
    python -m shorts_clipper chess <game.pgn | dir-of-pgns> [options]

Examples:
    python -m shorts_clipper clip https://youtu.be/xyz --output ./clips/
    python -m shorts_clipper autopilot --log-level DEBUG
    python -m shorts_clipper scout --count 3
    python -m shorts_clipper clip --source URL1 URL2 --continue-on-error
    python -m shorts_clipper autopilot --batch-file sources.txt
    python -m shorts_clipper inspect outputs/stock_short_1.mp4
    python -m shorts_clipper chess data/pgns --count 3
    python -m shorts_clipper chess game.pgn --no-music
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from shorts_clipper.core.logging import configure_logging
from shorts_clipper.core.settings import Settings


def _resolve_sources(args: argparse.Namespace) -> list[str]:
    """Explicit sources from ``--source`` / ``--batch-file`` / positional URL.

    ``--source`` wins over ``--batch-file``, which wins over the positional
    ``url``. ``--source`` value(s) may carry comma-separated URLs; the batch
    file holds one source per line with ``#`` comment lines allowed.
    Returns an empty list when no source is given.
    """
    sourced = getattr(args, "source", None)
    if sourced:
        tokens = sourced if isinstance(sourced, (list, tuple)) else [sourced]
        return [s.strip() for token in tokens for s in str(token).split(",") if s.strip()]

    batch_file = getattr(args, "batch_file", None)
    if batch_file:
        text = Path(batch_file).read_text(encoding="utf-8")
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    url = getattr(args, "url", None)
    if url:
        return [str(url).strip()]
    return []


def _cmd_batch(
    args: argparse.Namespace,
    settings: Settings,
    sources: list[str],
) -> int:
    """Run the pipeline once per explicit source and report per-source outcomes."""
    from shorts_clipper.pipeline.runner import BatchRunError, run_batch

    upload = getattr(args, "upload", False)
    count = getattr(args, "count", 1)
    niche = getattr(args, "niche", None)
    continue_on_error = getattr(args, "continue_on_error", False)

    print(f"🚀 BATCH START: {len(sources)} source(s) (fail-fast={not continue_on_error})")
    try:
        result = run_batch(
            sources,
            settings=settings,
            count=count,
            upload=upload,
            niche=niche,
            continue_on_error=continue_on_error,
        )
    except BatchRunError as exc:
        print(f"❌ BATCH ABORTED — {exc}")
        return 1

    for r in result.results:
        if r.ok:
            n = 0
            if r.outputs:
                n = len(r.outputs) if isinstance(r.outputs, list) else 1
            print(f"✅ [{r.index}/{result.total}] {r.source} — {n} clip(s)")
        else:
            print(f"❌ [{r.index}/{result.total}] {r.source} FAILED: {r.error}")

    if result.ok:
        print(f"\n🔥 BATCH SUCCESS — {result.succeeded}/{result.total} source(s) clipped.")
        return 0
    print(f"\n❌ BATCH FAILED — {result.failed}/{result.total} source(s) failed.")
    return 1


def _cmd_clip(args: argparse.Namespace, settings: Settings) -> int:
    sources = _resolve_sources(args)
    if not sources:
        print(
            "❌ No source given: pass a URL, --source URL1,URL2,..., or --batch-file file.txt",
            file=sys.stderr,
        )
        return 2

    if getattr(args, "source", None) or getattr(args, "batch_file", None):
        if args.output:
            print("❌ --output is not supported with --source / --batch-file.", file=sys.stderr)
            return 2
        return _cmd_batch(args, settings, sources)

    from shorts_clipper.pipeline.runner import run

    url = sources[0]
    out = Path(args.output) if args.output else None
    count = getattr(args, "count", 1)
    upload = getattr(args, "upload", False)

    source_title = None
    source_channel = None
    try:
        import subprocess

        from shorts_clipper.downloader.yt_dlp import get_base_yt_dlp_cmd

        cmd = get_base_yt_dlp_cmd()
        cmd.extend(["--skip-download", "--print", "%(title)s\n%(uploader)s", "--", url])
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
        lines = res.stdout.strip().split("\n")
        source_title = lines[0] if len(lines) > 0 else "YouTube Video"
        source_channel = lines[1] if len(lines) > 1 else ""
    except Exception as e:
        logging.getLogger(__name__).warning(
            "Failed to fetch video details via yt-dlp: %s. Using placeholders.", e
        )
        source_title = "Unknown Video"
        source_channel = "Unknown Channel"

    try:
        path_or_paths = run(
            url,
            settings=settings,
            output_path=out,
            count=count,
            upload=upload,
            source_title=source_title,
            source_channel=source_channel,
        )
        if isinstance(path_or_paths, list):
            print("\n🔥 Clips ready:")
            for p in path_or_paths:
                print(f"  - {p}")
        else:
            print(f"\n🔥 Clip ready: {path_or_paths}")
        return 0
    except Exception as exc:
        logging.getLogger(__name__).error("Pipeline failed: %s", exc)
        return 1


def _cmd_autopilot(args: argparse.Namespace, settings: Settings) -> int:
    sources = _resolve_sources(args)
    if sources:
        return _cmd_batch(args, settings, sources)

    from shorts_clipper.pipeline.runner import run_autopilot

    count = getattr(args, "count", 1)
    upload = getattr(args, "upload", False)
    path_or_paths = run_autopilot(
        settings=settings,
        channel=getattr(args, "channel", None),
        niche=getattr(args, "niche", None),
        keyword=getattr(args, "keyword", None),
        count=count,
        upload=upload,
    )
    if path_or_paths:
        if isinstance(path_or_paths, list):
            print("\n🔥 Clips ready:")
            for p in path_or_paths:
                print(f"  - {p}")
        else:
            print(f"\n🔥 Clip ready: {path_or_paths}")
        return 0
    print("❌ Autopilot could not find a suitable video.")
    return 1


def _cmd_scout(args: argparse.Namespace, settings: Settings) -> int:  # noqa: ARG001
    from shorts_clipper.scout.trending import get_trending_link

    count = getattr(args, "count", 1)
    found = 0
    while found < count:
        url = get_trending_link(
            channel=getattr(args, "channel", None),
            niche=getattr(args, "niche", None),
            keyword=getattr(args, "keyword", None),
            max_age_days=settings.scout_max_age_days,
        )
        if url:
            print(url)
            found += 1
        else:
            print("❌ No suitable video found.", file=sys.stderr)
            break
    return 0 if found == count else 1


def _cmd_web(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    from shorts_clipper.api.server import app

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8000)

    print(f"\n🚀 Launching Vanguard Clipper Web Console on http://{host}:{port}...")
    try:
        uvicorn.run(app, host=host, port=port)
        return 0
    except Exception as exc:
        print(f"❌ Failed to run Vanguard server: {exc}")
        return 1


def _cmd_repair_metadata(args: argparse.Namespace, settings: Settings) -> int:
    from shorts_clipper.cli.repair_metadata import run_repair

    return run_repair()


def _cmd_inspect(args: argparse.Namespace, settings: Settings) -> int:
    from shorts_clipper.inspect import run_inspect

    return run_inspect(args, settings)


def _cmd_cleanup(args: argparse.Namespace, settings: Settings) -> int:  # noqa: ARG001
    from shorts_clipper.core.cleanup import run_cleanup

    counts = run_cleanup(settings)
    print(
        f"Cleanup done: archived={counts['archived']} deleted_old={counts['deleted_old']} "
        f"deleted_excess={counts['deleted_excess']} deleted_stray={counts['deleted_stray']}"
    )
    return 0


def _cmd_chess_tactics(args: argparse.Namespace, settings: Settings) -> int:
    from shorts_clipper.chess import puzzle_db, tactics

    count = getattr(args, "count", 1)
    config_path = getattr(args, "tactics_config", None) or "config/chess_tactics.json"
    cfg = puzzle_db.TacticsConfig.from_file(config_path)
    cfg.db_path = Path(cfg.db_path)
    cfg.cache_path = Path(cfg.cache_path)
    used_path = cfg.cache_path.with_suffix(".used.json")

    if not cfg.db_path.is_file():
        print("📥 Lichess puzzle DB not found — downloading (~300 MB)...")
        puzzle_db.download_db(cfg.db_url, cfg.db_path)

    music = getattr(args, "music", None)
    no_music = getattr(args, "no_music", False)
    no_voice = getattr(args, "no_voice", False)
    output_dir = Path(getattr(args, "output", None) or "outputs/chess_tactics")
    output_dir.mkdir(parents=True, exist_ok=True)

    bed = None
    if not no_music:
        bed = Path(music) if music else Path(settings.music_dir) / "dark_industrial_loop.wav"
        if bed and not bed.is_file():
            print(f"⚠️  No music bed at {bed} — rendering without music.", file=sys.stderr)
            bed = None

    used = puzzle_db._load_used(used_path)
    puzzles = puzzle_db.select_puzzles(cfg.db_path, count=count, cfg=cfg, used=used)
    print(f"🎯 Selected {len(puzzles)} tactics from the Lichess DB")

    produced: list[Path] = []
    for i, puzzle in enumerate(puzzles, 1):
        out = output_dir / f"tactic_{i:03d}_{puzzle.id}.mp4"
        plan = tactics.plan_tactic(puzzle)
        print(f"  [{i}/{len(puzzles)}] {puzzle.id} — {plan.voice_lines[1]} — saving to {out.name}")
        result = tactics.render_tactic(plan, out, music_path=bed, voice=not no_voice)
        if result is not None:
            tactics.write_metadata(plan, out, cfg)
            produced.append(result)
            used.add(puzzle.id)

    puzzle_db._save_used(used_path, used)

    if produced:
        print(f"\n🔥 TACTICS SUCCESS — {len(produced)} clip(s) in {output_dir}")
        return 0
    print("\n❌ TACTICS FAILED — no clip produced.", file=sys.stderr)
    return 1


def _cmd_chess_analysis(
    args: argparse.Namespace,
    settings: Settings,
    fmt: str,
) -> int:
    """Run the real-game analysis format for a Lichess tournament or team."""
    from shorts_clipper.chess import analysis_format, batch, lichess

    paths = [str(p) for p in (getattr(args, "path", None) or [])]
    if not paths:
        print(
            "❌ No tournament given: pass a Lichess tournament URL or ID "
            "(e.g. shorts-clipper chess --format tournament https://lichess.org/tournament/MwiQDf4S)",
            file=sys.stderr,
        )
        return 2

    config_path = getattr(args, "analysis_config", None) or "config/chess_analysis.json"
    cfg = analysis_format.AnalysisConfig.from_file(config_path)

    critical_cp = getattr(args, "critical_cp", None)
    if critical_cp is not None:
        cfg.critical_cp = int(critical_cp)
    min_ply = getattr(args, "min_ply", None)
    if min_ply is not None:
        cfg.min_ply = int(min_ply)
    max_games = getattr(args, "max_games", None)
    if max_games is not None:
        cfg.max_games = int(max_games)

    count = getattr(args, "count", 1)
    output_dir = Path(getattr(args, "output", None) or "outputs/chess_analysis")
    output_dir.mkdir(parents=True, exist_ok=True)

    music = getattr(args, "music", None)
    no_music = getattr(args, "no_music", False)
    no_voice = getattr(args, "no_voice", False)
    continue_on_error = getattr(args, "continue_on_error", False)

    bed = None
    if not no_music:
        bed = Path(music) if music else Path(settings.music_dir) / batch.DEFAULT_CHESS_MUSIC
        if bed and not bed.is_file():
            print(f"⚠️  No music bed at {bed} — rendering without music.", file=sys.stderr)
            bed = None

    tournament_id = analysis_format.tournament_id_from_args(paths)
    if not tournament_id:
        print("❌ Could not parse a Lichess tournament id from the argument.", file=sys.stderr)
        return 2

    print(f"🎯 Fetching tournament {tournament_id}...")
    try:
        meta = lichess.fetch_tournament(tournament_id)
    except Exception as exc:
        print(f"❌ Could not fetch tournament {tournament_id}: {exc}", file=sys.stderr)
        return 1

    tournament_name = meta.get("fullName") or meta.get("name") or tournament_id
    print(f"📅 {tournament_name}")

    try:
        games = lichess.fetch_tournament_games(tournament_id)
    except Exception as exc:
        print(f"❌ Could not fetch games: {exc}", file=sys.stderr)
        return 1

    print(f"♟️  {len(games)} games fetched")

    club_members: list[str] = []
    if cfg.team_id:
        try:
            club_members = lichess.fetch_team_members(cfg.team_id)
            print(f"👥 {len(club_members)} club members on file")
        except Exception as exc:
            print(f"⚠️  Could not fetch team members: {exc}", file=sys.stderr)

    history = Path(getattr(args, "used_path", None) or batch.used_path(settings))
    used = batch.load_used_moments(history)

    decisions, stats = analysis_format.select_moments(
        games,
        count=count,
        cfg=cfg,
        club_members=club_members,
        used=used,
    )

    print(
        f"🔍 scanned={stats['scanned']} sampled={stats.get('sampled', stats['scanned'])} "
        f"too_short={stats['too_short']} no_moment={stats['no_moment']} "
        f"not_member={stats['not_member']} duplicate={stats['duplicate']}"
    )

    if not decisions:
        print(
            "❌ No decisive moment found above the threshold. "
            "Try --critical-cp or check the tournament has enough games.",
            file=sys.stderr,
        )
        return 1

    print(f"🎬 Rendering {len(decisions)} analysis short(s)...")
    produced: list[Path] = []
    for i, decision in enumerate(decisions, 1):
        white = analysis_format._player_name(decision.header, "white")  # noqa: SLF001
        black = analysis_format._player_name(decision.header, "black")  # noqa: SLF001
        slug = f"analysis_{i:03d}_{white}-{black}_m{decision.move_number}"
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug)
        out = output_dir / f"{slug}.mp4"
        plan = analysis_format.plan_analysis(decision, cfg)
        print(f"  [{i}/{len(decisions)}] {white} — {black}, ход {decision.move_number}")
        try:
            result = analysis_format.render_analysis(plan, out, music_path=bed, voice=not no_voice)
        except Exception:
            logging.getLogger(__name__).error("render failed", exc_info=True)
            result = None
        if result is None or not Path(result).is_file():
            print(f"❌ Render failed for {slug}", file=sys.stderr)
            if not continue_on_error:
                return 1
            continue
        analysis_format.write_metadata(plan, out, cfg)
        produced.append(Path(result))
        batch.record_used(history, batch.moment_key(decision))

    if produced:
        print(f"\n🔥 ANALYSIS SUCCESS — {len(produced)} clip(s) in {output_dir}")
        return 0
    print("\n❌ ANALYSIS FAILED — no clip produced.", file=sys.stderr)
    return 1


def _cmd_chess_club_challenge(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    """Run the club-challenge format for a Lichess tournament or team."""
    from shorts_clipper.chess import batch, challenge_format, lichess

    paths = [str(p) for p in (getattr(args, "path", None) or [])]
    if not paths:
        print(
            "❌ No tournament given: pass a Lichess tournament URL or ID "
            "(e.g. shorts-clipper chess --format club-challenge https://lichess.org/tournament/MwiQDf4S)",
            file=sys.stderr,
        )
        return 2

    config_path = getattr(args, "challenge_config", None) or "config/chess_challenges.json"
    cfg = challenge_format.ChallengeConfig.from_file(config_path)

    min_ply = getattr(args, "min_ply", None)
    if min_ply is not None:
        cfg.min_ply = int(min_ply)
    max_games = getattr(args, "max_games", None)
    if max_games is not None:
        cfg.max_games = int(max_games)

    count = getattr(args, "count", 1)
    output_dir = Path(getattr(args, "output", None) or "outputs/chess_club_challenges")
    output_dir.mkdir(parents=True, exist_ok=True)

    music = getattr(args, "music", None)
    no_music = getattr(args, "no_music", False)
    no_voice = getattr(args, "no_voice", False)
    continue_on_error = getattr(args, "continue_on_error", False)

    bed = None
    if not no_music:
        bed = Path(music) if music else Path(settings.music_dir) / batch.DEFAULT_CHESS_MUSIC
        if bed and not bed.is_file():
            print(f"⚠️  No music bed at {bed} — rendering without music.", file=sys.stderr)
            bed = None

    tournament_id = challenge_format.tournament_id_from_args(paths)
    if not tournament_id:
        print("❌ Could not parse a Lichess tournament id from the argument.", file=sys.stderr)
        return 2

    print(f"🎯 Fetching tournament {tournament_id}...")
    try:
        meta = lichess.fetch_tournament(tournament_id)
    except Exception as exc:
        print(f"❌ Could not fetch tournament {tournament_id}: {exc}", file=sys.stderr)
        return 1

    tournament_name = meta.get("fullName") or meta.get("name") or tournament_id
    print(f"📅 {tournament_name}")

    try:
        games = lichess.fetch_tournament_games(tournament_id)
    except Exception as exc:
        print(f"❌ Could not fetch games: {exc}", file=sys.stderr)
        return 1

    print(f"♟️  {len(games)} games fetched")

    club_members: list[str] = []
    team_id = cfg.team_id or challenge_format._team_id_from_url(cfg.lichess_team_url)  # noqa: SLF001
    if team_id:
        try:
            club_members = lichess.fetch_team_members(team_id)
            print(f"👥 {len(club_members)} club members on file")
        except Exception as exc:
            print(f"⚠️  Could not fetch team members: {exc}", file=sys.stderr)

    history = Path(getattr(args, "used_path", None) or batch.used_path(settings))
    used = batch.load_used_moments(history)

    candidates = challenge_format.find_challenges_in_games(games, cfg, club_members=club_members)

    selected: list[tuple[object, dict, int]] = []
    skipped = 0
    for challenge, headers, rating in candidates:
        key = batch.script_hash(f"{challenge.fen} {challenge.best_uci}")
        if key in used:
            skipped += 1
            continue
        selected.append((challenge, headers, rating))
        if len(selected) >= count:
            break

    print(f"🔍 found={len(candidates)} selected={len(selected)} duplicate={skipped}")

    if not selected:
        print(
            "❌ No challenge position found above the threshold. "
            "Try --min-ply / --max-games or check the tournament has enough games.",
            file=sys.stderr,
        )
        return 1

    print(f"🎬 Rendering {len(selected)} challenge short(s)...")
    produced: list[Path] = []
    for i, (challenge, headers, _rating) in enumerate(selected, 1):
        white = challenge_format._player_name(headers, "white")  # noqa: SLF001
        black = challenge_format._player_name(headers, "black")  # noqa: SLF001
        slug = f"challenge_{i:03d}_{white}-{black}_m{challenge.move_number}"
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug)
        out = output_dir / f"{slug}.mp4"
        plan = challenge_format.plan_challenge_game(challenge, headers, cfg)
        print(
            f"  [{i}/{len(selected)}] {white} — {black}, ход {challenge.move_number}, {challenge.best_san}"
        )
        try:
            result = challenge_format.render_challenge(
                plan, out, music_path=bed, voice=not no_voice
            )
        except Exception:
            logging.getLogger(__name__).error("render failed", exc_info=True)
            result = None
        if result is None or not Path(result).is_file():
            print(f"❌ Render failed for {slug}", file=sys.stderr)
            if not continue_on_error:
                return 1
            continue
        challenge_format.write_metadata(plan, out, cfg)
        produced.append(Path(result))
        batch.record_used(history, batch.script_hash(f"{challenge.fen} {challenge.best_uci}"))

    if produced:
        print(f"\n🔥 CHALLENGE SUCCESS — {len(produced)} clip(s) in {output_dir}")
        return 0
    print("\n❌ CHALLENGE FAILED — no clip produced.", file=sys.stderr)
    return 1


def _cmd_chess_story(args: argparse.Namespace, settings: Settings) -> int:
    """Run the human-story format for a Lichess tournament or custom JSON beats."""
    from shorts_clipper.chess import batch, lichess, stories

    paths = [str(p) for p in (getattr(args, "path", None) or [])]
    config_path = getattr(args, "story_config", None) or "config/chess_stories.json"
    cfg = stories.StoryConfig.from_file(config_path)

    count = getattr(args, "count", 1)
    output_dir = Path(getattr(args, "output", None) or "outputs/chess_stories")
    output_dir.mkdir(parents=True, exist_ok=True)

    music = getattr(args, "music", None)
    no_music = getattr(args, "no_music", False)
    no_voice = getattr(args, "no_voice", False)
    continue_on_error = getattr(args, "continue_on_error", False)

    bed = None
    if not no_music:
        bed = Path(music) if music else Path(settings.music_dir) / batch.DEFAULT_CHESS_MUSIC
        if bed and not bed.is_file():
            print(f"⚠️  No music bed at {bed} — rendering without music.", file=sys.stderr)
            bed = None

    template = getattr(args, "story_template", "tournament") or "tournament"

    produced: list[Path] = []

    # Custom JSON beats path.
    if paths and Path(paths[0]).is_file() and Path(paths[0]).suffix.lower() == ".json":
        json_path = Path(paths[0])
        print(f"📖 Loading story beats from {json_path}")
        try:
            beats = stories.parse_beats_from_json(json_path)
        except Exception as exc:
            print(f"❌ Could not parse story JSON: {exc}", file=sys.stderr)
            return 1
        if template == "member":
            # A JSON sidecar may override member fields; turn it into a profile.
            sidecar = json.loads(json_path.read_text(encoding="utf-8"))
            username = sidecar.get("username") or "Игрок"
            beats = stories.build_member_story(username, sidecar, cfg)
        plan = stories.plan_story(beats, cfg, voice=not no_voice)
        out = output_dir / f"story_custom_{json_path.stem}.mp4"
        print(f"  [1/1] custom story — saving to {out.name}")
        try:
            result = stories.render_story(plan, out, music_path=bed, voice=not no_voice)
        except Exception:
            logging.getLogger(__name__).error("story render failed", exc_info=True)
            result = None
        if result is None or not Path(result).is_file():
            print("❌ Render failed for custom story", file=sys.stderr)
            return 1
        stories.write_metadata(plan, out, cfg)
        produced.append(Path(result))
        print(f"\n🔥 STORY SUCCESS — {len(produced)} clip(s) in {output_dir}")
        return 0

    # Lichess tournament recap.
    if not paths:
        print(
            "❌ No source given: pass a Lichess tournament URL/ID or a JSON story file.",
            file=sys.stderr,
        )
        return 2

    tournament_id = stories.tournament_id_from_args(paths)
    if not tournament_id:
        print("❌ Could not parse a Lichess tournament id from the argument.", file=sys.stderr)
        return 2

    print(f"🎯 Fetching tournament {tournament_id}...")
    try:
        meta = lichess.fetch_tournament(tournament_id)
    except Exception as exc:
        print(f"❌ Could not fetch tournament {tournament_id}: {exc}", file=sys.stderr)
        return 1

    tournament_name = meta.get("fullName") or meta.get("name") or tournament_id
    print(f"📅 {tournament_name}")

    beats = stories.build_tournament_recap(meta, cfg)
    plan = stories.plan_story(beats, cfg, voice=not no_voice)

    print("🎬 Rendering story short...")
    for i in range(1, count + 1):
        out = output_dir / f"story_{i:03d}_{tournament_id}.mp4"
        print(f"  [{i}/{count}] tournament recap — saving to {out.name}")
        try:
            result = stories.render_story(plan, out, music_path=bed, voice=not no_voice)
        except Exception:
            logging.getLogger(__name__).error("story render failed", exc_info=True)
            result = None
        if result is None or not Path(result).is_file():
            print(f"❌ Render failed for {out.name}", file=sys.stderr)
            if not continue_on_error:
                return 1
            continue
        stories.write_metadata(plan, out, cfg)
        produced.append(Path(result))

    if produced:
        print(f"\n🔥 STORY SUCCESS — {len(produced)} clip(s) in {output_dir}")
        return 0
    print("\n❌ STORY FAILED — no clip produced.", file=sys.stderr)
    return 1


def _cmd_chess(args: argparse.Namespace, settings: Settings) -> int:
    from shorts_clipper.chess import analysis

    if not analysis.available():
        print(
            '❌ python-chess is not installed. Install the extra: pip install -e ".[chess]"',
            file=sys.stderr,
        )
        return 2

    fmt = getattr(args, "format", "deciding") or "deciding"
    if fmt == "tactic":
        return _cmd_chess_tactics(args, settings)
    if fmt in ("tournament", "analysis"):
        return _cmd_chess_analysis(args, settings, fmt)
    if fmt == "club-challenge":
        return _cmd_chess_club_challenge(args, settings)
    if fmt == "story":
        return _cmd_chess_story(args, settings)

    from shorts_clipper.chess import batch

    if getattr(args, "clear_used", False):
        history = Path(args.used_path) if args.used_path else batch.used_path(settings)
        dropped = batch.clear_used(history)
        print(f"🧹 Cleared {dropped} chess moment(s) from {history}")
        if not getattr(args, "path", None):
            return 0

    paths = [str(p) for p in (getattr(args, "path", None) or [])]
    if not paths:
        print(
            "❌ No PGN given: pass a file or a directory "
            "(e.g. shorts-clipper chess data/pgns --count 2)",
            file=sys.stderr,
        )
        return 2

    count = getattr(args, "count", 1)
    continue_on_error = getattr(args, "continue_on_error", False)
    music = getattr(args, "music", None)
    no_music = getattr(args, "no_music", False)
    if no_music:
        music = None

    if not no_music:
        bed = Path(music) if music else Path(settings.music_dir) / batch.DEFAULT_CHESS_MUSIC
        if not bed.is_file():
            print(f"⚠️  No music bed at {bed} — rendering silent.", file=sys.stderr)

    print(
        f"♟️  CHESS BATCH START: {len(paths)} path(s), --count {count} "
        f"(fail-fast={not continue_on_error})"
    )
    try:
        result = batch.run_batch(
            paths,
            settings=settings,
            count=count,
            critical_cp=getattr(args, "critical_cp", None),
            min_ply=getattr(args, "min_ply", None),
            output_dir=getattr(args, "output", None),
            music=music,
            no_music=no_music,
            seed=getattr(args, "seed", batch.DEFAULT_SEED),
            continue_on_error=continue_on_error,
            used_file=getattr(args, "used_path", None),
            fmt=getattr(args, "format", "deciding") or "deciding",
            keep_runs=getattr(args, "keep_runs", 3),
        )
    except batch.ChessBatchError as exc:
        print(f"❌ CHESS BATCH ABORTED — {exc}")
        return 1

    for r in result.results:
        if r.ok:
            detail = f"{len(r.clips)} clip(s)"
            if r.skipped_used:
                detail += f", {r.skipped_used} already cut"
            if r.games_in_file > 1:
                detail += f" (file holds {r.games_in_file} games, used the first)"
            print(f"✅ [{r.index}/{result.total}] {r.source} — {detail}")
        else:
            print(f"❌ [{r.index}/{result.total}] {r.source} FAILED: {r.error}")

    if not result.clips:
        print(
            "❌ No clip produced: no game yielded a moment above the threshold"
            + (
                f" ({result.skipped_duplicate} already cut — try --clear-used)"
                if result.skipped_duplicate
                else ""
            ),
            file=sys.stderr,
        )

    if result.ok and result.clips:
        print("\n🔥 CHESS BATCH SUCCESS — " + ", ".join(str(p) for p in result.clips))
        return 0
    if result.ok and not result.clips:
        print("\n❌ CHESS BATCH FAILED — nothing was clipped.")
        return 1
    print(f"\n❌ CHESS BATCH FAILED — {result.failed}/{result.total} source(s) failed.")
    return 1


def _cmd_doctor(args: argparse.Namespace, settings: Settings) -> int:  # noqa: ARG001
    from shorts_clipper.cli.doctor import run_doctor

    return run_doctor(settings)


def _cmd_retention_report(args: argparse.Namespace, settings: Settings) -> int:
    from shorts_clipper.cli.retention_report import run_retention_report

    return run_retention_report(settings, args)


def _cmd_revenue_report(args: argparse.Namespace, settings: Settings) -> int:
    from shorts_clipper.cli.revenue_report import run_revenue_report

    return run_revenue_report(settings, args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m shorts_clipper",
        description="AI-powered viral shorts clipping pipeline.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--env",
        default=".env",
        metavar="FILE",
        help="Path to .env file (default: .env)",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # ── clip ──────────────────────────────────────────────────────────────
    clip_p = sub.add_parser("clip", help="Clip a specific YouTube video.")
    clip_p.add_argument("url", nargs="?", help="YouTube video URL.")
    clip_p.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help="Output file path (default: outputs/clip_TIMESTAMP.mp4)",
    )
    clip_p.add_argument(
        "-c",
        "--count",
        type=int,
        default=1,
        help="Number of viral clips to extract per source (default: 1)",
    )
    clip_p.add_argument(
        "--upload",
        action="store_true",
        help="Upload the resulting clips to YouTube Shorts",
    )
    clip_p.add_argument(
        "--source",
        nargs="+",
        metavar="URL",
        help="Batch: one or more YouTube URLs/IDs to clip sequentially "
        "(comma-separated lists are also accepted).",
    )
    clip_p.add_argument(
        "--batch-file",
        metavar="FILE",
        help="Batch: text file with one YouTube URL/ID per line "
        "(blank lines and lines starting with '#' are ignored).",
    )
    clip_p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Batch: keep going after a failed source instead of failing fast "
        "(the overall run still exits non-zero).",
    )

    # ── autopilot ─────────────────────────────────────────────────────────
    autopilot_p = sub.add_parser(
        "autopilot",
        help="Scout a trending video and clip it automatically.",
    )
    autopilot_p.add_argument(
        "--channel",
        help="Search only this channel's recent videos.",
    )
    autopilot_p.add_argument(
        "--niche",
        help="Build 5 targeted search queries around this niche and rotate between them.",
    )
    autopilot_p.add_argument(
        "--keyword",
        help="Search specifically for this term across multiple platforms.",
    )
    autopilot_p.add_argument(
        "-c",
        "--count",
        type=int,
        default=1,
        help="Number of viral clips to extract (default: 1)",
    )
    autopilot_p.add_argument(
        "--upload",
        action="store_true",
        help="Upload the resulting clips to YouTube Shorts",
    )
    autopilot_p.add_argument(
        "--source",
        nargs="+",
        metavar="URL",
        help="Batch: one or more YouTube URLs/IDs to clip sequentially, "
        "skipping discovery (comma-separated lists are also accepted).",
    )
    autopilot_p.add_argument(
        "--batch-file",
        metavar="FILE",
        help="Batch: text file with one YouTube URL/ID per line "
        "(blank lines and lines starting with '#' are ignored).",
    )
    autopilot_p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Batch: keep going after a failed source instead of failing fast "
        "(the overall run still exits non-zero).",
    )

    # ── scout ─────────────────────────────────────────────────────────────
    scout_p = sub.add_parser("scout", help="Print trending video URLs and exit.")
    scout_p.add_argument(
        "-n",
        "--count",
        type=int,
        default=1,
        help="Number of URLs to find (default: 1)",
    )
    scout_p.add_argument(
        "--channel",
        help="Search only this channel's recent videos.",
    )
    scout_p.add_argument(
        "--niche",
        help="Build 5 targeted search queries around this niche and rotate between them.",
    )
    scout_p.add_argument(
        "--keyword",
        help="Search specifically for this term across multiple platforms.",
    )

    # ── web ───────────────────────────────────────────────────────────────
    web_p = sub.add_parser("web", help="Start the Vanguard Web Console Dashboard.")
    web_p.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind to (default: 127.0.0.1)",
    )
    web_p.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000)",
    )

    # ── inspect ─────────────────────────────────────────────────────────────
    inspect_p = sub.add_parser(
        "inspect",
        help="Print a read-only quality report for a rendered short.",
    )
    inspect_p.add_argument("file", help="Path to the rendered .mp4 file.")

    # ── repair-metadata ───────────────────────────────────────────────────────────────
    sub.add_parser("repair-metadata", help="Repair clips missing metadata.")

    # ── cleanup ────────────────────────────────────────────────────────────────────────
    sub.add_parser("cleanup", help="Archive published clips and prune old output files.")

    # ── doctor ─────────────────────────────────────────────────────────────────────────
    sub.add_parser("doctor", help="Check local environment and setup readiness.")

    # ── retention-report ──────────────────────────────────────────────────────────────────
    retention_p = sub.add_parser(
        "retention-report",
        help="Decision-science retention report per platform/niche from the metrics DB.",
    )
    retention_p.add_argument(
        "--platform",
        default=None,
        help="Only report rows for this platform (default: all).",
    )
    retention_p.add_argument(
        "--days",
        type=int,
        default=30,
        help="Lookback window in days for published clips (default: 30).",
    )
    retention_p.add_argument(
        "--niche",
        default=None,
        help="Only report rows for this niche (default: all).",
    )
    retention_p.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="Path to the JSON report; the Markdown report is written next to it "
        "(default: outputs/retention_report.json).",
    )

    # ── chess ─────────────────────────────────────────────────────────────────
    chess_p = sub.add_parser(
        "chess",
        help="Cut chess shorts from a PGN, a directory of PGNs, or both.",
    )
    chess_p.add_argument(
        "path",
        nargs="*",
        metavar="PATH",
        help="PGN file and/or directory of .pgn files. For --format tournament, "
        "--format analysis or --format club-challenge, pass a Lichess "
        "tournament URL or ID. With no path, --clear-used just resets the "
        "dedup history.",
    )
    chess_p.add_argument(
        "-o",
        "--output",
        metavar="DIR",
        default=None,
        help="Output directory (default: outputs/chess)",
    )
    chess_p.add_argument(
        "-c",
        "--count",
        type=int,
        default=1,
        help="Moments to cut across the whole run, best N first (default: 1)",
    )
    chess_p.add_argument(
        "--critical-cp",
        type=int,
        default=None,
        help="Minimum evaluation loss in centipawns for a move to count (default: 200)",
    )
    chess_p.add_argument(
        "--min-ply",
        type=int,
        default=None,
        help="Ignore the first N plies so 'critical move' is not move 4 (default: 10)",
    )
    chess_p.add_argument(
        "--max-games",
        type=int,
        default=None,
        help="For tournament/analysis/club-challenge formats: analyse at most N games (default: from config)",
    )
    chess_p.add_argument(
        "--music",
        metavar="FILE",
        default=None,
        help="Music bed; defaults to dark_industrial_loop.wav under SHORTS_MUSIC_DIR",
    )
    chess_p.add_argument("--no-music", action="store_true", help="Render without a bed")
    chess_p.add_argument(
        "--seed",
        type=int,
        default=7,
        help="Seed for the bed offset (default: 7)",
    )
    chess_p.add_argument(
        "--used-path",
        metavar="FILE",
        default=None,
        help="Dedup history file (default: data/chess_used.json)",
    )
    chess_p.add_argument(
        "--format",
        choices=(
            "deciding",
            "challenge",
            "opening",
            "endgame",
            "highlight",
            "tactic",
            "tournament",
            "analysis",
            "club-challenge",
            "story",
        ),
        default="deciding",
        help=(
            "Content format: 'deciding' cuts the move that lost the game, "
            "'challenge' asks a position as a puzzle from a PGN (needs the engine), "
            "'club-challenge' fetches a Lichess tournament and turns its games into "
            "viewer challenges (needs the engine), 'opening' names the line and its "
            "first mistake, 'endgame' names the complex, 'highlight' skims the whole "
            "game fast then slows down at its worst move (one clip per game), "
            "'tactic' uses the curated Lichess puzzle DB, 'tournament'/'analysis' "
            "fetches a Lichess tournament and renders decisive moments from real games, "
            "'story' renders human-centric tournament recaps or member profiles "
            "(default: deciding)"
        ),
    )
    chess_p.add_argument(
        "--tactics-config",
        metavar="FILE",
        default=None,
        help="Path to tactics quality-gate config (default: config/chess_tactics.json)",
    )
    chess_p.add_argument(
        "--analysis-config",
        metavar="FILE",
        default=None,
        help="Path to analysis format config (default: config/chess_analysis.json)",
    )
    chess_p.add_argument(
        "--challenge-config",
        metavar="FILE",
        default=None,
        help="Path to club-challenge format config (default: config/chess_challenges.json)",
    )
    chess_p.add_argument(
        "--story-config",
        metavar="FILE",
        default=None,
        help="Path to story format config (default: config/chess_stories.json)",
    )
    chess_p.add_argument(
        "--story-template",
        choices=("tournament", "member"),
        default="tournament",
        help="Story template when loading a JSON sidecar (default: tournament)",
    )
    chess_p.add_argument(
        "--no-voice",
        action="store_true",
        help="Render tactic shorts without TTS voiceover",
    )
    chess_p.add_argument(
        "--clear-used",
        action="store_true",
        help="Forget every moment cut so far, so this run may re-cut them",
    )
    chess_p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Batch: keep going after a failed PGN instead of failing fast "
        "(the overall run still exits non-zero).",
    )
    chess_p.add_argument(
        "--keep-runs",
        type=int,
        default=3,
        metavar="N",
        help="How many past run_* folders to keep in the output directory; older "
        "ones are deleted (default: 3). 0 keeps none.",
    )

    # ── revenue-report ───────────────────────────────────────────────────────────
    revenue_p = sub.add_parser(
        "revenue-report",
        help="Affiliate income report (total revenue, platform/niche and per-partner "
        "breakdown) from the affiliate_events table in the metrics DB.",
    )
    revenue_p.add_argument(
        "--niche",
        default=None,
        help="Only report rows for this niche (default: all).",
    )
    revenue_p.add_argument(
        "--partner",
        default=None,
        help="Only report rows for this partner id (default: all).",
    )
    revenue_p.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="Path to the Markdown report (default: outputs/revenue_report.md).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.log_level)
    settings = Settings.from_env(env_path=args.env)

    dispatch = {
        "clip": _cmd_clip,
        "autopilot": _cmd_autopilot,
        "scout": _cmd_scout,
        "web": _cmd_web,
        "inspect": _cmd_inspect,
        "repair-metadata": _cmd_repair_metadata,
        "cleanup": _cmd_cleanup,
        "doctor": _cmd_doctor,
        "retention-report": _cmd_retention_report,
        "revenue-report": _cmd_revenue_report,
        "chess": _cmd_chess,
    }
    return dispatch[args.command](args, settings)


if __name__ == "__main__":
    sys.exit(main())
