"""Every story in the library must pass the correctness gate (links, reachability, endings)."""
import glob
import json
import os

import pytest

import story_engine as E

STORIES = sorted(glob.glob(os.path.join(E.STORIES_DIR, "*.json")))


def test_library_not_empty():
    assert STORIES, "no stories found in the library"


@pytest.mark.parametrize("path", STORIES, ids=os.path.basename)
def test_story_is_valid(path):
    with open(path, encoding="utf-8") as f:
        story = json.load(f)
    problems = E.validate_story_dict(story)
    assert not problems, "\n".join(problems)
