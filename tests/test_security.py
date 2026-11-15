"""Story text is untrusted (model output from a visitor's theme): it must not be able to inject
HTML or remote images into pages that render it with unsafe_allow_html."""
import json
import os

import story_engine as E

EVIL = {
    "title": "<img src=x onerror=alert(1)>Gate",
    "theme": "<style>body{display:none}</style>",
    "difficulty": "easy",
    "goal": "Win </div><iframe src='https://evil.example'></iframe>",
    "prologue": "Look ![pixel](https://evil.example/t.png) and 2 < 3, a <3 heart.",
    "locations": {"a<b": {"description": "<script>x</script>", "choices": [{"text": "<b>go</b>", "target_id": "a<b"}]}},
}


def test_clean_text_neutralises_tags_and_images_but_keeps_prose():
    assert "<" not in E.clean_text("<script>alert(1)</script><!-- x --><?php ?>")
    assert E.clean_text("2 < 3 and a <3 heart, x<=y") == "2 < 3 and a <3 heart, x<=y"
    assert "![" not in E.clean_text("![a](http://x/y.png)")
    once = E.clean_text("<b>hi</b> ![a](b)")
    assert E.clean_text(once) == once                      # idempotent: load -> save -> load is stable


def test_clean_story_walks_values_not_keys():
    c = E.clean_story(EVIL)
    assert "a<b" in c["locations"]                         # ids untouched
    flat = json.dumps({k: v for k, v in c.items() if k != "locations"}) + json.dumps(list(c["locations"].values()))
    assert "<img" not in flat and "<style" not in flat and "<iframe" not in flat and "<script" not in flat
    assert "2 < 3" in c["prologue"] and EVIL["title"].startswith("<img")   # a copy; the input is not modified


def test_library_io_is_clean_and_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "STORIES_DIR", str(tmp_path))
    raw = tmp_path / "evil.json"
    raw.write_text(json.dumps(EVIL), encoding="utf-8")     # e.g. a file that arrived from S3
    meta = E.list_stories()[0]
    assert "<" not in meta["title"] + meta["theme"] + meta["goal"]
    assert "<script" not in E.load_story_file(str(raw))["locations"]["a<b"]["description"]
    assert E.list_stories()[0] == meta                     # served from the cache...
    EVIL2 = dict(EVIL, title="Renamed")
    raw.write_text(json.dumps(EVIL2), encoding="utf-8")
    os.utime(raw, ns=(1, 1))                               # ...until the file changes
    assert E.list_stories()[0]["title"] == "Renamed"
    saved = tmp_path / "saved.json"
    E.save_story_file(EVIL, str(saved))
    assert "<img" not in saved.read_text(encoding="utf-8")
