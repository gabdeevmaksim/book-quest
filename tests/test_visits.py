"""visits.py — visit / unique-visitor counter (temp SQLite, no network)."""
import os

import pytest

import visits as V


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("QUEST_VISITS_DB", str(tmp_path / "visits.db"))


def test_visits_and_unique_visitors():
    for who in ("1.2.3.4", "1.2.3.4", "5.6.7.8"):
        assert V.record_visit(who)
    t = V.totals()
    assert t == {"visits": 3, "visitors": 2, "visits_today": 3, "visitors_today": 2}


def test_same_visitor_on_two_days_is_one_unique():
    V.record_visit("1.2.3.4", now=1_790_000_000)
    V.record_visit("1.2.3.4", now=1_790_000_000 + 86_400 * 2)
    t = V.totals()
    assert t["visits"] == 2 and t["visitors"] == 1
    assert [r[2] for r in V.daily()] == [1, 1]                 # one unique on each day


def test_ip_is_never_stored_and_salt_is_stable(tmp_path):
    V.record_visit("9.9.9.9")
    raw = open(os.environ["QUEST_VISITS_DB"], "rb").read()
    assert b"9.9.9.9" not in raw
    assert V.visitor_hash("9.9.9.9") == V.visitor_hash("9.9.9.9") != V.visitor_hash("9.9.9.8")
