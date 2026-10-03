"""Smoke tests that run the real Streamlit app headlessly (streamlit.testing.AppTest).
They catch crashes on the main screens — e.g. a Streamlit release that removes an API we use."""
import glob
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
