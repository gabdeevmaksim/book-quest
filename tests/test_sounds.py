"""Sound effects: the clips exist, and the queue/switch logic in sounds.py behaves."""
import os

import streamlit as st

import sounds


def test_clips_exist_and_are_small():
    for name in sounds.NAMES:
        path = os.path.join(sounds.SOUND_DIR, f"{name}.mp3")
        assert os.path.exists(path), f"missing {path} — run scripts/make_sounds.py"
        assert os.path.getsize(path) < 40_000
    assert set(sounds._sources()) == set(sounds.NAMES)


def test_queue_dedupes_and_respects_the_switch(monkeypatch):
    sent = []
    monkeypatch.setattr(sounds, "_inject", sent.append)
    st.session_state.clear()
    sounds.play("item"); sounds.play("item"); sounds.play("nope")
    assert st.session_state[sounds.QUEUE_KEY] == ["item"]
    sounds.flush()
    assert len(sent) == 1 and '["item"]' in sent[0]
    assert sounds.QUEUE_KEY not in st.session_state
    st.session_state[sounds.PREF_KEY] = False            # switched off: nothing queued, nothing sent
    sounds.play("item"); sounds.play_now("roll"); sounds.flush()
    assert len(sent) == 1
    st.session_state.clear()


def test_env_switch_turns_everything_off(monkeypatch):
    monkeypatch.setenv("QUEST_SOUND", "0")
    assert not sounds.available() and not sounds.enabled()


def test_init_script_carries_the_clips_only_when_on():
    assert "data:audio/mpeg;base64," in sounds.init_html(True)
    assert "data:audio/mpeg;base64," not in sounds.init_html(False)
