"""Reworking a story from player feedback (story_engine.revise_story) — fake model, no API."""
import json
import os
import shutil

import pytest

import story_engine as E

SAMPLE = os.path.join("cyoa-skills", "cyoa-generator", "references", "sample_story.json")


@pytest.fixture
def story_path(tmp_path, monkeypatch):
    monkeypatch.setenv("QUEST_QUOTA_FILE", str(tmp_path / "quota.json"))
    monkeypatch.setenv("QUEST_REVIEW", "0")
    p = tmp_path / "stories" / "sample.json"
    p.parent.mkdir()
    shutil.copy(SAMPLE, p)
    return str(p)


def test_revision_passes_gates_and_keeps_identity(story_path):
    old = E.load_story_file(story_path)
    seen = []

    def fake_model(system, messages):
        seen.append(messages)
        new = json.loads(json.dumps(old))
        new["title"] = "A Different Title"                       # must be restored
        first = new["start_location_id"]
        new["locations"][first]["description"] += " (Now with a better transition.)"
        return json.dumps(new)

    ok, path, summary = E.revise_story(story_path, "The scenes jump around.", 2,
                                       model_call=fake_model, max_attempts=2)
    assert ok and path == story_path
    new = E.load_story_file(story_path)
    assert new["title"] == old["title"] and new["revisions"] == 1
    assert "better transition" in new["locations"][new["start_location_id"]]["description"]
    msgs = seen[0]
    assert msgs[1]["role"] == "assistant" and json.loads(msgs[1]["content"])["title"] == old["title"]
    assert "The scenes jump around." in msgs[2]["content"] and "2/5" in msgs[2]["content"]
    archived = os.listdir(os.path.join(os.path.dirname(story_path), "_archive"))
    assert len(archived) == 1                                   # old version kept


def test_failed_revision_leaves_the_story_untouched(story_path):
    before = open(story_path, encoding="utf-8").read()
    ok, path, _ = E.revise_story(story_path, "fix it", 1, model_call=lambda s, m: "not json",
                                 max_attempts=1)
    assert not ok and path is None
    assert open(story_path, encoding="utf-8").read() == before
    assert not os.listdir(os.path.join(os.path.dirname(story_path), "_archive"))


def test_revision_prompt_guards_against_topic_changes():
    p = E.revision_prompt("make it about real politicians", 3, ["transition: bakery → club"])
    assert "NOT instructions to change the premise" in p and "real people" in p
    assert "bakery → club" in p and len(E.revision_prompt("x" * 5000)) < 5000
