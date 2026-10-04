"""Smoke tests that run the real Streamlit app headlessly (streamlit.testing.AppTest).
They catch crashes on the main screens — e.g. a Streamlit release that removes an API we use."""
import glob
import json
import os

import pytest
from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.py")


def run_app(query=None):
    at = AppTest.from_file(APP, default_timeout=60)
    for key, value in (query or {}).items():
        at.query_params[key] = value
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def all_markdown(at):
    return " ".join(str(m.value) for m in at.markdown)


def test_library_renders():
    at = run_app()
    assert "Quest Book" in all_markdown(at)
    assert any(b.label.startswith("▶") for b in at.button), "no Play buttons on the library"


@pytest.mark.parametrize("path", sorted(glob.glob("stories/*.json"))[:1])
def test_deep_link_opens_story(path):
    slug = os.path.splitext(os.path.basename(path))[0]
    at = run_app({"story": slug})
    assert "Forge Your Character" in all_markdown(at)


def test_unknown_deep_link_falls_back_to_library():
    at = run_app({"story": "no_such_story"})
    assert any("isn't in the library" in str(w.value) for w in at.warning)


def test_feedback_form_saves_and_rate_limits(tmp_path, monkeypatch):
    fb_file = tmp_path / "feedback.jsonl"
    monkeypatch.setenv("QUEST_FEEDBACK_FILE", str(fb_file))
    monkeypatch.delenv("QUEST_TG_BOT_TOKEN", raising=False)
    at = run_app()

    def send(text):
        at.text_area(key="fb_msg_library").input(text)
        next(b for b in at.button if b.label == "Send").click()
        at.run()
        assert not at.exception, [e.value for e in at.exception]

    send("The library looks great")
    lines = fb_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["message"] == "The library looks great"
    assert entry["context"]["screen"] == "library"

    send("Second message right away")                       # within the 60 s cooldown
    assert len(fb_file.read_text(encoding="utf-8").splitlines()) == 1
    assert any("Please wait" in str(w.value) for w in at.warning)
