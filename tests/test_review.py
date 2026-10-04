"""The story-review agent (narrative_review.py) and its place as the 4th gate. No API calls:
the reviewer and the generator are faked."""
import json
import os

import narrative_review as NR
import story_engine as E

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "cyoa-skills", "cyoa-generator", "references", "sample_story.json")
SAMPLE_TEXT = open(SAMPLE, encoding="utf-8").read()
SAMPLE_STORY = json.loads(SAMPLE_TEXT)

MAJOR = json.dumps({"issues": [{"type": "transition", "severity": "major", "location": "hall",
                                "choice": "Enter the ossuary", "problem": "arrives in the wrong room",
                                "fix": "describe the skull arch"}]})
MINOR = json.dumps({"issues": [{"type": "introduced", "severity": "minor", "location": "cistern",
                                "problem": "the gold is mentioned a bit early"}]})
CLEAN = '{"issues": []}'


def test_outline_has_paths_texts_and_markers():
    o = NR.outline(SAMPLE_STORY)
    assert "## sealed_well" in o and "reached from: cistern, sunken_vault" in o
    assert "success: Rung by rung" in o and "MONSTER Bone Sentinel" in o
    assert "[ENDING: victory]" in o


def test_parse_normalises_and_rejects_garbage():
    issues = NR.parse("```json\n" + MAJOR + "\n```", SAMPLE_STORY)
    assert issues[0]["severity"] == "major" and issues[0]["location"] == "hall"
    odd = NR.parse('{"issues":[{"severity":"HUGE","type":"weird","location":"nowhere","problem":"x"}]}',
                   SAMPLE_STORY)
    assert odd[0]["severity"] == "minor" and odd[0]["type"] == "transition" and "(?)" in odd[0]["location"]
    assert NR.parse("I could not review this.") is None


def test_verdicts():
    assert NR.review_story(SAMPLE_STORY, lambda s, m: MAJOR)["status"] == "REVIEW"
    minor = NR.review_story(SAMPLE_STORY, lambda s, m: MINOR)
    assert minor["status"] == "OK" and minor["minors"] == 1
    assert NR.review_story(SAMPLE_STORY, lambda s, m: CLEAN)["status"] == "OK"


def test_failures_never_block():
    def boom(system, messages):
        raise RuntimeError("API down")
    assert NR.review_story(SAMPLE_STORY, boom)["status"] == "skipped"
    assert NR.review_story(SAMPLE_STORY, lambda s, m: "not json")["status"] == "skipped"


def _green_gates(monkeypatch):
    monkeypatch.setattr(E, "gate_report", lambda p, d: (
        True, [], {"correctness": True, "coherence": True, "balance": "PASS", "bal_lines": []}))


def test_major_findings_go_back_into_the_repair_loop(monkeypatch, tmp_path):
    _green_gates(monkeypatch)
    prompts, verdicts = [], iter([MAJOR, CLEAN])

    def generator(system, messages):
        prompts.append(messages[-1]["content"])
        return SAMPLE_TEXT

    ok, path, summary = E.create_story("catacombs", "easy", api_key="x", out_path=str(tmp_path / "s.json"),
                                       model_call=generator, review=True,
                                       review_call=lambda s, m: next(verdicts))
    assert ok and summary["review"] == "OK"
    assert len(prompts) == 2 and "NARRATIVE" in prompts[1] and "arrives in the wrong room" in prompts[1]


def test_review_skipped_when_gates_fail_or_review_off(monkeypatch, tmp_path):
    def must_not_run(system, messages):
        raise AssertionError("the review should not run")
    monkeypatch.setattr(E, "gate_report", lambda p, d: (
        False, ["BALANCE — too soft"], {"correctness": True, "coherence": True,
                                        "balance": "ADJUST", "bal_lines": []}))
    ok, _, summary = E.create_story("x", "easy", api_key="x", max_attempts=1, review=True,
                                    model_call=lambda s, m: SAMPLE_TEXT, review_call=must_not_run)
    assert not ok and summary["review"] == "not run"

    _green_gates(monkeypatch)
    ok, _, summary = E.create_story("x", "easy", api_key="x", out_path=str(tmp_path / "s.json"),
                                    review=False, model_call=lambda s, m: SAMPLE_TEXT,
                                    review_call=must_not_run)
    assert ok and summary["review"] == "off"
