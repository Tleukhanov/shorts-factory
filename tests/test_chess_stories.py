"""Tests for the human-story chess content format."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from shorts_clipper import __main__ as cli
from shorts_clipper.chess import stories
from shorts_clipper.core.settings import Settings


@pytest.fixture
def cfg():
    return stories.StoryConfig(
        club_name="TestClub",
        lichess_team_url="https://lichess.org/team/test",
        whatsapp_url="https://chat.whatsapp.com/test",
        hashtags=("#test",),
        presenter_asset="assets/presenter/placeholder.png",
        background_color="#1a1a2e",
        text_color="#ffffff",
    )


def test_config_from_file(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(
        json.dumps(
            {
                "club_name": "TestClub",
                "lichess_team_url": "https://lichess.org/team/test",
                "whatsapp_url": "https://chat.whatsapp.com/test",
                "hashtags": ["#test"],
                "presenter_asset": "assets/presenter/placeholder.png",
                "background_color": "#000000",
                "text_color": "#ffffff",
                "cta_top": "Join us",
                "cta_bottom": "Link below",
            }
        ),
        encoding="utf-8",
    )
    cfg = stories.StoryConfig.from_file(path)
    assert cfg.club_name == "TestClub"
    assert cfg.whatsapp_url == "https://chat.whatsapp.com/test"
    assert cfg.hashtags == ("#test",)
    assert cfg.cta_top == "Join us"


def test_default_config_has_sensible_values():
    cfg = stories.StoryConfig()
    assert cfg.club_name
    assert cfg.lichess_team_url
    assert cfg.presenter_asset


def test_build_tournament_recap_populates_beats(cfg):
    meta = {
        "fullName": "Test Arena",
        "startsAt": "2024-06-15T18:00:00Z",
        "variant": {"name": "Стандарт"},
        "stats": {"berserkCount": 7},
        "players": {
            "players": [
                {"name": "alice", "score": {"rating": 2100}},
                {"name": "bob", "score": {"rating": 2050}},
                {"name": "carol", "score": {"rating": 2000}},
            ]
        },
    }
    beats = stories.build_tournament_recap(meta, cfg)
    assert len(beats) == 4
    assert beats[0].kind == "hook"
    assert "Test Arena" in beats[0].text
    assert "alice" in beats[2].text
    assert "2100" in beats[2].text
    assert beats[3].kind == "cta"
    assert cfg.club_name in beats[3].text


def test_build_tournament_recap_handles_empty_podium(cfg):
    meta = {"fullName": "Empty Arena", "players": {"players": []}}
    beats = stories.build_tournament_recap(meta, cfg)
    assert any("Итоги турнира" in b.text for b in beats)


def test_build_member_story_from_api_data(cfg):
    info = {
        "username": "denis",
        "title": "FM",
        "perfs": {"classical": {"rating": 2300}, "rapid": {"rating": 2250}},
    }
    beats = stories.build_member_story("denis", info, cfg)
    assert len(beats) == 4
    assert "FM denis" in beats[0].text
    assert "2300" in beats[1].text


def test_build_member_story_from_sidecar(cfg):
    sidecar = {
        "username": "elena",
        "rating": 1800,
        "best_result": "Победительница клубного турнира 2024",
    }
    beats = stories.build_member_story("elena", sidecar, cfg)
    assert "elena" in beats[0].text
    assert "1800" in beats[1].text
    assert "Победительница" in beats[2].text


def test_plan_story_computes_holds_and_segments(cfg):
    beats = [
        stories.StoryBeat(kind="hook", text="Привет!"),
        stories.StoryBeat(kind="context", text="Это короткий текст."),
        stories.StoryBeat(kind="cta", text="Подпишись!"),
    ]
    plan = stories.plan_story(beats, cfg, voice=False)
    assert len(plan.holds) == 3
    assert plan.total_duration == pytest.approx(sum(plan.holds))
    assert len(plan.voice_segments) == 3
    assert plan.voice_segments[0][1] == 0.0


def test_plan_story_estimates_from_word_count(cfg):
    beats = [stories.StoryBeat(kind="hook", text="Один два три четыре пять")]
    plan = stories.plan_story(beats, cfg, voice=False)
    # Five words / 2.6 wps + hook padding.
    assert plan.holds[0] > 1.9


def test_parse_beats_from_json_list(tmp_path):
    path = tmp_path / "beats.json"
    path.write_text(
        json.dumps(
            [
                {"kind": "hook", "text": "H1"},
                {"kind": "context", "text": "C1", "asset_path": "bg.jpg"},
            ]
        ),
        encoding="utf-8",
    )
    beats = stories.parse_beats_from_json(path)
    assert len(beats) == 2
    assert beats[1].asset_path == "bg.jpg"


def test_parse_beats_from_json_dict(tmp_path):
    path = tmp_path / "beats.json"
    path.write_text(
        json.dumps({"beats": [{"kind": "cta", "text": "C1"}]}),
        encoding="utf-8",
    )
    beats = stories.parse_beats_from_json(path)
    assert len(beats) == 1
    assert beats[0].kind == "cta"


def test_write_metadata_contains_title_and_links(tmp_path, cfg):
    beats = [
        stories.StoryBeat(kind="hook", text="История игрока"),
        stories.StoryBeat(kind="cta", text="Подпишись"),
    ]
    plan = stories.plan_story(beats, cfg, voice=False)
    out = tmp_path / "clip.mp4"
    meta = stories.write_metadata(plan, out, cfg)
    text = meta.read_text(encoding="utf-8")
    assert "История игрока" in text
    assert "TestClub" in text
    assert cfg.lichess_team_url in text
    assert cfg.whatsapp_url in text
    assert "#test" in text


def test_render_story_without_voice_produces_video(tmp_path, cfg):
    beats = [
        stories.StoryBeat(kind="hook", text="Кто победил?"),
        stories.StoryBeat(kind="context", text="Три игрока, один победитель."),
        stories.StoryBeat(kind="cta", text="Вступай в клуб!"),
    ]
    plan = stories.plan_story(beats, cfg, voice=False)
    out = tmp_path / "story.mp4"
    result = stories.render_story(plan, out, music_path=None, voice=False)
    assert result is not None
    assert Path(result).is_file()
    assert Path(result).stat().st_size > 1000


def test_render_story_works_without_presenter_asset(tmp_path):
    cfg = stories.StoryConfig(presenter_asset="assets/presenter/missing.png")
    beats = [stories.StoryBeat(kind="hook", text="Без аватара")]
    plan = stories.plan_story(beats, cfg, voice=False)
    out = tmp_path / "story_no_avatar.mp4"
    result = stories.render_story(plan, out, music_path=None, voice=False)
    assert result is not None
    assert Path(result).is_file()


def test_tournament_id_from_args():
    assert stories.tournament_id_from_args([]) == ""
    assert stories.tournament_id_from_args(["MwiQDf4S"]) == "MwiQDf4S"
    assert (
        stories.tournament_id_from_args(["https://lichess.org/tournament/MwiQDf4S"])
        == "MwiQDf4S"
    )


def test_parser_accepts_story_format():
    parser = cli.build_parser()
    args = parser.parse_args(
        ["chess", "https://lichess.org/tournament/MwiQDf4S", "--format", "story"]
    )
    assert args.format == "story"


def test_story_command_smoke(tmp_path, cfg):
    """The CLI branch wires fetch, plan, render and metadata together."""
    root = Path(tmp_path)
    args = cli.build_parser().parse_args(
        [
            "chess",
            "https://lichess.org/tournament/abc",
            "--format",
            "story",
            "--story-config",
            str(root / "cfg.json"),
            "--output",
            str(root / "out"),
            "--count",
            "1",
            "--no-music",
            "--no-voice",
        ]
    )
    cfg_path = root / "cfg.json"
    cfg_path.write_text(
        json.dumps(
            {
                "club_name": cfg.club_name,
                "lichess_team_url": cfg.lichess_team_url,
                "whatsapp_url": cfg.whatsapp_url,
                "hashtags": list(cfg.hashtags),
                "presenter_asset": cfg.presenter_asset,
                "background_color": cfg.background_color,
                "text_color": cfg.text_color,
                "cta_top": cfg.cta_top,
                "cta_bottom": cfg.cta_bottom,
            }
        ),
        encoding="utf-8",
    )

    settings = Settings(
        music_dir=root / "music",
        chess_used_path=root / "used.json",
    )

    meta = {
        "fullName": "Smoke Arena",
        "startsAt": "2024-01-01T12:00:00Z",
        "variant": {"name": "Стандарт"},
        "stats": {"berserkCount": 3},
        "players": {
            "players": [
                {"name": "alice", "score": {"rating": 2000}},
                {"name": "bob", "score": {"rating": 1900}},
                {"name": "carol", "score": {"rating": 1800}},
            ]
        },
    }

    with (
        mock.patch("shorts_clipper.chess.lichess.fetch_tournament", return_value=meta),
        mock.patch(
            "shorts_clipper.chess.stories.render_story",
            side_effect=lambda plan, out, **kw: Path(out).write_bytes(b"") or Path(out),
        ),
        mock.patch("shorts_clipper.chess.stories.write_metadata") as write_meta,
    ):
        code = cli._cmd_chess_story(args, settings)

    assert code == 0
    assert write_meta.call_count == 1
