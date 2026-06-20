import streamlit as st
import json
import random
import os
import time
import copy
import glob
import re
import subprocess
from functools import lru_cache

st.set_page_config(
    page_title="CYOA RPG Adventure",
    page_icon="🎲",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Special+Elite&family=Share+Tech+Mono&display=swap');

[data-testid="stAppViewContainer"] { background-color: #0f0d0a; }
[data-testid="stHeader"]           { background-color: #0f0d0a; }
[data-testid="stSidebar"]          { background-color: #111009; border-right: 1px solid #2a2418; }

body, p, li, div { color: #c8b49a; }

h1 {
    font-family: 'Special Elite', Georgia, serif !important;
    color: #d4a843 !important;
    text-align: center !important;
    letter-spacing: 3px !important;
    border-bottom: 1px solid #3a2e18 !important;
    padding-bottom: 0.5rem !important;
    margin-bottom: 0.2rem !important;
}
h2, h3 { color: #b89a6a !important; font-family: 'Special Elite', Georgia, serif !important; }

.stCaption p { color: #6a5a42 !important; font-size: 0.8rem !important; }

/* Stat metrics */
[data-testid="stMetric"] {
    background: #141008;
    border: 1px solid #2a2010;
    border-radius: 5px;
    padding: 0.3rem 0.5rem;
}
[data-testid="stMetricLabel"]  p { color: #6a5a42 !important; font-size: 0.72rem !important; font-family: 'Share Tech Mono', monospace !important; }
[data-testid="stMetricValue"]    { color: #d4a843 !important; font-size: 1.1rem !important;  font-family: 'Share Tech Mono', monospace !important; }
[data-testid="stMetricDelta"]    { display: none !important; }

/* Buttons */
[data-testid="stButton"] > button {
    background-color: #161208 !important;
    color: #b8a07a !important;
    border: 1px solid #3a2e14 !important;
    border-radius: 3px !important;
    font-family: 'Share Tech Mono', 'Courier New', monospace !important;
    font-size: 0.88rem !important;
    width: 100% !important;
    text-align: left !important;
    padding: 0.7em 1.1em !important;
    min-height: 2.8em !important;
    line-height: 1.4 !important;
    transition: all 0.12s ease !important;
    white-space: normal !important;
    word-break: break-word !important;
}
[data-testid="stButton"] > button:hover {
    background-color: #201a0c !important;
    border-color: #d4a843 !important;
    color: #f0d890 !important;
}
[data-testid="stButton"] > button:active {
    background-color: #2a2210 !important;
}

/* Expander */
[data-testid="stExpander"] summary       { color: #7a6a4a !important; font-family: 'Share Tech Mono', monospace !important; font-size: 0.82rem !important; }
[data-testid="stExpander"] [role="group"]{ background: #0c0a07 !important; border: none !important; }

/* Divider */
hr { border-color: #2a2418 !important; margin: 0.8rem 0 !important; }

/* Alert boxes */
[data-testid="stAlert"] { border-radius: 3px !important; }

/* Sidebar text */
[data-testid="stSidebar"] p, [data-testid="stSidebar"] li { font-size: 0.83rem; color: #9a8a6a; }
[data-testid="stSidebar"] h3 { font-size: 1rem !important; color: #d4a843 !important; border-bottom: 1px solid #2a2010; padding-bottom: 4px; }
</style>
""", unsafe_allow_html=True)

DICE_FACES = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]

# Support / donations — Ko-fi is live; swap in your own page if it changes.
KOFI_URL = "https://ko-fi.com/dedulek"

from story_engine import (  # Streamlit-free core (shared with story_agent.py)
    DIFFICULTIES, PROVIDER_LABEL, PROVIDER_PKG,
    gen_provider, gen_default_model, env_api_key,
    list_stories, load_story_file, unique_story_path, save_story_file,
    validate_story_dict, balance_check, generate_story_api,
    gen_models, create_story, push_story_to_git,
    s3_enabled, push_story_to_s3, sync_stories_from_s3,
    monthly_budget, month_spend, budget_exceeded, record_spend, free_fallback_models,
)


# ── dice & text helpers ───────────────────────────────────────────────────────


def roll_dice(dice_type="1d6"):
    num, sides = map(int, dice_type.split("d"))
    return sum(random.randint(1, sides) for _ in range(num))


@lru_cache(maxsize=None)
def _dice_sums(dice_type="1d6"):
    """All equally-likely totals for a dice expression (e.g. 2d6 -> 36 outcomes)."""
    num, sides = map(int, dice_type.split("d"))
    sums = [0]
    for _ in range(num):
        sums = [t + face for t in sums for face in range(1, sides + 1)]
    return tuple(sums)


def pass_probability(dice_type, need):
    """P(dice roll >= need). need = check_value - attribute - bonuses."""
    outs = _dice_sums(dice_type)
    if not outs:
        return 0.0
    return sum(1 for o in outs if o >= need) / len(outs)


def odds_label(dice_type, check_value, attr_val, bonus=0):
    pct = round(pass_probability(dice_type, check_value - attr_val - bonus) * 100)
    return f"≈{pct}%"


def animate_roll(placeholder, dice_type="1d6"):
    num = int(dice_type.split("d")[0])
    result = roll_dice(dice_type)
    for _ in range(16):
        faces = " ".join(random.choice(DICE_FACES) for _ in range(min(num, 3)))
        placeholder.markdown(
            f"<div style='text-align:center;font-size:3.4rem;letter-spacing:10px;"
            f"padding:0.6rem 0;color:#d4a843'>{faces}</div>",
            unsafe_allow_html=True,
        )
        time.sleep(0.055)
    placeholder.markdown(
        f"<div style='text-align:center;font-size:2rem;font-weight:bold;"
        f"color:#d4a843;padding:0.6rem 0'>🎲 {result}</div>",
        unsafe_allow_html=True,
    )
    time.sleep(0.45)
    return result


def item_name(story, item_id):
    return story.get("items", {}).get(item_id, {}).get("name", item_id)


def item_icon(story, item_id):
    return story.get("items", {}).get(item_id, {}).get("icon", "📦")


# ── inventory ─────────────────────────────────────────────────────────────────

def apply_loot(story, loc):
    """Grant items found in a location on first visit."""
    looted = st.session_state.setdefault("looted", set())
    loc_id = st.session_state.current_loc
    if loc_id in looted:
        return
    for item_id in loc.get("loot", []):
        if item_id not in st.session_state.inventory:
            st.session_state.inventory.append(item_id)
            st.session_state.log.append(
                f"🎒 Found: {item_icon(story, item_id)} {item_name(story, item_id)}"
            )
    if loc.get("loot"):
        looted.add(loc_id)


def use_item(story, item_id):
    """Apply a consumable item's `use` effect, then remove it from inventory."""
    item = story.get("items", {}).get(item_id, {})
    effect = item.get("use") or {}
    heal = effect.get("heal", 0)
    if heal:
        before = st.session_state.hp
        st.session_state.hp = min(st.session_state.max_hp, st.session_state.hp + heal)
        gained = st.session_state.hp - before
        st.session_state.log.append(
            f"➕ Used {item_icon(story, item_id)} {item_name(story, item_id)} "
            f"(+{gained} HP, now {st.session_state.hp}/{st.session_state.max_hp})"
        )
    if item_id in st.session_state.inventory:
        st.session_state.inventory.remove(item_id)


def render_inventory(story):
    st.sidebar.markdown("### 🎒 Inventory")
    inv = st.session_state.get("inventory", [])
    if not inv:
        st.sidebar.caption("*Nothing yet.*")
    else:
        alive = not st.session_state.get("game_over") and st.session_state.get("hp", 0) > 0
        at_full = st.session_state.get("hp", 0) >= st.session_state.get("max_hp", 1)
        for item_id in inv:
            item = story.get("items", {}).get(item_id, {})
            icon = item.get("icon", "📦")
            name = item.get("name", item_id)
            desc = item.get("description", "")
            st.sidebar.markdown(
                f"<span style='background:#1e1a0e;border:1px solid #5a4520;"
                f"border-radius:12px;padding:2px 10px;font-size:0.8rem;"
                f"color:#d4a843;font-family:monospace'>{icon} {name}</span>",
                unsafe_allow_html=True,
            )
            if desc:
                st.sidebar.caption(desc)
            # consumable items get a Use button
            if item.get("use") and alive:
                if st.sidebar.button(
                    f"Use {name}",
                    key=f"use_{item_id}",
                    disabled=at_full and "heal" in item["use"],
                    help="Already at full HP." if (at_full and "heal" in item["use"]) else None,
                ):
                    use_item(story, item_id)
                    st.rerun()


# ── game state ────────────────────────────────────────────────────────────────

def restart(story, keep_char=False):
    """Reset to a fresh run of the SAME story. keep_char preserves rolled attributes/max HP."""
    attrs  = st.session_state.get("attributes")
    max_hp = st.session_state.get("max_hp")
    path   = st.session_state.get("active_story_path")
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.session_state.active_story      = story
    st.session_state.active_story_path = path
    if keep_char and attrs is not None:
        st.session_state.attributes         = attrs
        st.session_state.max_hp             = max_hp
        st.session_state.hp                 = max_hp
        st.session_state.current_loc        = story["start_location_id"]
        st.session_state.log                = []
        st.session_state.game_over          = False
        st.session_state.inventory          = []
        st.session_state.locations          = copy.deepcopy(story["locations"])
        st.session_state.char_creation_done = True
        st.session_state.pending_choice     = None
        st.session_state.pending_combat     = False


def apply_choice_target(choice, story):
    st.session_state.current_loc = choice["target_id"]
    for item_id in _coerce_list(choice.get("gives_item")):
        if item_id not in st.session_state.inventory:
            st.session_state.inventory.append(item_id)
            st.session_state.log.append(
                f"🎒 Received: {item_icon(story, item_id)} {item_name(story, item_id)}"
            )
    # optional inline effects
    heal = choice.get("heals", 0)
    if heal:
        before = st.session_state.hp
        st.session_state.hp = min(st.session_state.max_hp, st.session_state.hp + heal)
        st.session_state.log.append(f"➕ Recovered {st.session_state.hp - before} HP.")
    for item_id in _coerce_list(choice.get("consumes_item")):
        if item_id in st.session_state.inventory:
            st.session_state.inventory.remove(item_id)


def _coerce_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _item_bonus(cond):
    """Return (bonus, item_id) if the player holds a condition's bonus item."""
    ib = cond.get("item_bonus")
    if ib and ib.get("item") in st.session_state.get("inventory", []):
        return ib.get("bonus", 0), ib.get("item")
    return 0, None


# ── dice resolution ───────────────────────────────────────────────────────────

def resolve_choice(choice, story):
    if "condition" not in choice:
        apply_choice_target(choice, story)
        return

    cond = choice["condition"]
    attr       = cond["attribute"]
    check_val  = cond["check_value"]
    dice       = cond.get("dice_type", "1d6")
    fail_dmg   = cond.get("fail_damage", 2)

    bonus, bonus_item = _item_bonus(cond)

    placeholder = st.empty()
    roll = animate_roll(placeholder, dice)
    player_val = st.session_state.attributes.get(attr, 0)
    total = roll + player_val + bonus

    bonus_txt = f"+{bonus}({item_name(story, bonus_item)})" if bonus else ""

    if total >= check_val:
        st.session_state.log.append(
            f"✅ {attr.upper()} DC {check_val} — passed! {roll}+{player_val}{bonus_txt}={total}"
        )
        apply_choice_target(choice, story)
    else:
        st.session_state.log.append(
            f"❌ {attr.upper()} DC {check_val} — failed. {roll}+{player_val}{bonus_txt}={total}. "
            f"Lost {fail_dmg} HP."
        )
        st.session_state.hp -= fail_dmg
        if st.session_state.hp <= 0:
            st.session_state.game_over = True
        fail_target = choice.get("fail_target") or cond.get("fail_target")
        if fail_target:
            st.session_state.current_loc = fail_target


def resolve_combat(monster, loc_id, story):
    dice     = monster.get("dice_type", "1d6")
    fail_dmg = monster.get("fail_damage", 4)
    attr     = monster.get("attribute", "strength")

    placeholder = st.empty()
    roll = animate_roll(placeholder, dice)
    attr_val = st.session_state.attributes.get(attr, 0)
    total   = roll + attr_val

    if total >= monster["strength"]:
        st.session_state.log.append(
            f"⚔️ Defeated {monster['name']}! "
            f"{roll}+{attr.upper()}({attr_val})={total} vs DC {monster['strength']}."
        )
        del st.session_state.locations[loc_id]["monster"]
    else:
        st.session_state.log.append(
            f"💥 {monster['name']} wounds you! "
            f"{roll}+{attr.upper()}({attr_val})={total} vs DC {monster['strength']}. "
            f"Lost {fail_dmg} HP."
        )
        st.session_state.hp -= fail_dmg
        if st.session_state.hp <= 0:
            st.session_state.game_over = True


# ── screens ───────────────────────────────────────────────────────────────────

def show_char_creation(story):
    if st.button("←  Library", key="cc_back"):
        go_to_library()
        st.rerun()
    st.markdown("<h1>⚔️ Forge Your Character</h1>", unsafe_allow_html=True)

    if story.get("prologue"):
        st.markdown(
            f"<div style='background:#100d08;border:1px solid #2a2418;border-left:3px solid #6a5a2a;"
            f"border-radius:0 6px 6px 0;padding:1.1rem 1.4rem;margin:0.6rem 0;"
            f"font-family:\"Special Elite\",Georgia,serif;font-size:0.98rem;line-height:1.85;"
            f"color:#bfae8e'>{story['prologue']}</div>",
            unsafe_allow_html=True,
        )

    if story.get("goal"):
        st.markdown(
            f"<div style='background:#0f1a0f;border:1px solid #2a4a2a;border-radius:4px;"
            f"padding:0.7rem 1rem;font-size:0.85rem;color:#6a9a6a;"
            f"font-family:monospace;margin:0.5rem 0'>"
            f"🎯 <strong>Goal:</strong> {story['goal']}</div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        "<div style='background:#141008;border-left:3px solid #8b6914;"
        "border-radius:0 6px 6px 0;padding:1.2rem 1.6rem;margin:1rem 0;"
        "font-family:\"Special Elite\",Georgia,serif;font-size:1rem;"
        "line-height:1.85;color:#d4c5a9'>"
        "Before your journey begins, fate must decide your strengths. "
        "Roll <strong>2d6</strong> for each attribute — this is who you are. "
        "<em>You roll once. Fate is fate.</em>"
        "</div>",
        unsafe_allow_html=True,
    )

    template = story["character_template"]
    attrs  = ["strength", "agility", "stamina"]
    labels = {"strength": "💪 Strength", "agility": "🏃 Agility", "stamina": "🫁 Stamina"}
    descs  = {
        "strength": "Raw power — fighting, lifting, forcing",
        "agility":  "Speed & finesse — dodging, sneaking, climbing",
        "stamina":  "Endurance — heat, poison, exhaustion",
    }

    if "char_rolls" not in st.session_state:
        st.session_state.char_rolls = {}

    st.divider()

    # single roll — no re-rolling (prevents save-scumming)
    if not st.session_state.char_rolls:
        if st.button("🎲  Roll All Attributes", use_container_width=True):
            cols         = st.columns(3)
            placeholders = {}
            for i, attr in enumerate(attrs):
                with cols[i]:
                    st.caption(labels[attr])
                    placeholders[attr] = st.empty()
            for attr in attrs:
                st.session_state.char_rolls[attr] = animate_roll(placeholders[attr], "2d6")
            st.rerun()
        else:
            st.info("Click the button above to roll your attributes.")
        return

    cols = st.columns(3)
    for i, attr in enumerate(attrs):
        with cols[i]:
            st.metric(labels[attr], st.session_state.char_rolls.get(attr, "?"))
            st.caption(descs[attr])
    st.divider()
    st.caption(f"Starting HP: **{template['health']}**")
    if st.button("⚔️  Begin Adventure", use_container_width=True):
        final = template.copy()
        for attr in attrs:
            final[attr] = st.session_state.char_rolls[attr]
        del st.session_state.char_rolls
        st.session_state.attributes         = final
        st.session_state.hp                 = template["health"]
        st.session_state.max_hp             = template["health"]
        st.session_state.current_loc        = story["start_location_id"]
        st.session_state.log                = []
        st.session_state.game_over          = False
        st.session_state.inventory          = []
        st.session_state.locations          = copy.deepcopy(story["locations"])
        st.session_state.char_creation_done = True
        st.session_state.pending_choice     = None
        st.session_state.pending_combat     = False
        st.rerun()


def show_end_buttons(story):
    c1, c2, c3 = st.columns(3)
    if c1.button("↩  Play Again (same hero)", use_container_width=True):
        restart(story, keep_char=True)
        st.rerun()
    if c2.button("🎲  New Character", use_container_width=True):
        restart(story, keep_char=False)
        st.rerun()
    if c3.button("📚  Story Library", use_container_width=True):
        go_to_library()
        st.rerun()


def go_to_library():
    """Drop the active story/run and return to the gallery."""
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.session_state.screen = "library"


def select_story(path):
    """Make `path` the active story and begin a fresh run (character creation)."""
    story = load_story_file(path)
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.session_state.active_story      = story
    st.session_state.active_story_path = path
    st.session_state.screen            = "game"


# ── library / create screens ──────────────────────────────────────────────────

def _difficulty_badge(diff):
    colors = {"easy": ("#1f3a1f", "#7fd17f"), "normal": ("#3a2e10", "#e8b94a"),
              "hard": ("#3a1414", "#e07a7a")}
    bg, fg = colors.get(diff, ("#222018", "#9a8a6a"))
    return (f"<span style='background:{bg};color:{fg};border:1px solid {fg}55;"
            f"border-radius:10px;padding:1px 9px;font-size:0.7rem;font-family:monospace;"
            f"letter-spacing:1px'>{(diff or '—').upper()}</span>")


def _draft_badge(is_draft):
    if not is_draft:
        return ""
    return ("<span style='background:#2a1c08;color:#e0a64a;border:1px solid #e0a64a55;"
            "border-radius:10px;padding:1px 8px;font-size:0.7rem;font-family:monospace;"
            "letter-spacing:1px;margin-right:5px'>DRAFT</span>")


def _lang_tag(s):
    lang = (s.get("language") or "").strip()
    if not lang or lang.lower() == "english":
        return ""
    lvl = (s.get("language_level") or "").strip()
    return f" · 🗣 {lang}" + (f" ({lvl})" if lvl else "")


def show_library():
    st.markdown("<h1>📖 Quest Book</h1>", unsafe_allow_html=True)
    st.caption("Choose your adventure — or forge a new one.")

    n, errs = st.session_state.get("s3_sync_info", (0, []))
    if errs:
        st.warning("Cloud story sync had problems: " + " · ".join(errs[:3]))
    elif n:
        st.caption(f"☁️ {n} stor{'y' if n == 1 else 'ies'} synced from cloud storage.")

    if st.button("✨  Create a New Story", use_container_width=True):
        st.session_state.screen = "create"
        st.session_state.pop("gen_result", None)
        st.rerun()

    st.divider()

    stories = list_stories()
    if not stories:
        st.info("No stories yet. Click **Create a New Story** above to generate your first adventure.")
        return

    cols = st.columns(2)
    for i, s in enumerate(stories):
        with cols[i % 2]:
            if s.get("error"):
                st.error(f"⚠ {os.path.basename(s['path'])}: {s['error']}")
                continue
            goal = (s["goal"][:150] + "…") if len(s["goal"]) > 150 else s["goal"]
            st.markdown(
                f"<div style='background:linear-gradient(135deg,#141008,#0f0c06);"
                f"border:1px solid #2a2010;border-left:3px solid #8b6914;border-radius:0 6px 6px 0;"
                f"padding:0.9rem 1.1rem;margin:0.3rem 0;min-height:9rem'>"
                f"<div style='display:flex;justify-content:space-between;align-items:flex-start;gap:8px'>"
                f"<span style='color:#d4a843;font-family:\"Special Elite\",Georgia,serif;font-size:1.05rem;line-height:1.3'>{s['title']}</span>"
                f"<span style='white-space:nowrap'>{_draft_badge(s.get('draft'))}{_difficulty_badge(s['difficulty'])}</span></div>"
                f"<div style='color:#6a5a42;font-size:0.74rem;font-family:monospace;margin:0.25rem 0 0.5rem'>"
                f"🌍 {s['theme']} · {s['n']} locations{_lang_tag(s)}</div>"
                f"<div style='color:#a99878;font-size:0.84rem;line-height:1.5'>{goal}</div></div>",
                unsafe_allow_html=True,
            )
            if st.button("▶  Play", key=f"play_{s['path']}", use_container_width=True):
                select_story(s["path"])
                st.rerun()

    st.divider()
    st.markdown(
        f"<div style='text-align:center;margin:0.3rem 0'>"
        f"<a href='{KOFI_URL}' target='_blank' style='color:#d4a843;text-decoration:none;"
        f"font-family:\"Share Tech Mono\",monospace;font-size:0.85rem;border:1px solid #3a2e14;"
        f"border-radius:4px;padding:0.55rem 1.1rem;background:#161208'>"
        f"☕  Enjoying the quests? Support Quest Book on Ko-fi</a></div>",
        unsafe_allow_html=True,
    )


def _push_story_to_git(path):
    """Commit + push the new story (story_engine.push_story_to_git). Non-fatal, but the
    outcome is RETURNED so the UI can show why a push didn't happen instead of hiding it."""
    return push_story_to_git(path)


def _do_generate(theme, difficulty, length, title_hint, api_key, provider, model,
                 language="English", language_level="C2"):
    # Monthly budget policy: while under the cap, use the owner's chosen (paid) model first,
    # with the provider chain as automatic fallback. Once this month's paid spend reaches the
    # cap, switch generation to the FREE Google chain; if there's no Google key for that
    # backup, pause creation (the library stays fully playable). create_story runs the FULL
    # gated pipeline (validate -> coherence -> balance, with repair) and only returns ok=True
    # once every gate passes.
    capped = False
    if budget_exceeded():
        google_key = env_api_key("google")
        if not google_key:
            return {"ok": False, "capped_blocked": True,
                    "spend": round(month_spend(), 2), "budget": round(monthly_budget(), 2)}
        capped, provider, api_key = True, "google", google_key
        models = free_fallback_models()
    else:
        models = [model] + [m for m in gen_models(provider) if m != model]
    try:
        ok, path, summary = create_story(theme, difficulty, length, title_hint, api_key,
                                         provider=provider, models=models, max_attempts=5,
                                         keep_best=True, language=language,
                                         language_level=language_level)
    except ImportError:
        pkg = PROVIDER_PKG.get(provider, provider)
        return {"ok": False, "errors": [f"The '{pkg}' Python package isn't installed. "
                                        f"Install it with:  pip install {pkg}"]}
    except Exception as e:
        return {"ok": False, "errors": [f"Generation failed: {e}"]}

    # bank this generation's cost against the monthly budget (≈0 when on the free chain)
    if summary and summary.get("cost_usd") is not None:
        record_spend(summary.get("cost_usd", 0.0), summary.get("model_used", ""),
                     summary.get("tokens_in", 0), summary.get("tokens_out", 0))
    if ok:
        pushed, push_msg = _push_story_to_git(path)
        title = load_story_file(path).get("title") or theme
        out = {"ok": True, "path": path, "title": title,
               "pushed": pushed, "push_msg": push_msg,
               "verdict": summary["balance"], "vlines": summary["bal_lines"], "gates": summary,
               "capped": capped, "cost_usd": summary.get("cost_usd"),
               "model_used": summary.get("model_used"), "attempts": summary.get("attempts"),
               "spend": round(month_spend(), 2), "budget": round(monthly_budget(), 2)}
        if s3_enabled():
            out["s3_ok"], out["s3_msg"] = push_story_to_s3(path)
        return out
    if path:   # gates not fully met / a model limit was hit — best draft was kept
        pushed, push_msg = _push_story_to_git(path)
        title = load_story_file(path).get("title") or theme
        reasons = []
        if summary and not summary.get("correctness"):
            reasons.append("valid links/reachability")
        if summary and not summary.get("coherence"):
            reasons.append("coherence (loops or thin opening)")
        if summary and summary.get("balance") != "PASS":
            reasons.append(f"balance ({summary.get('balance')}) for '{difficulty}'")
        out = {"ok": False, "draft": True, "path": path, "title": title, "reasons": reasons,
               "pushed": pushed, "push_msg": push_msg,
               "verdict": (summary or {}).get("balance", "—"),
               "vlines": (summary or {}).get("bal_lines", []),
               "limit": (summary or {}).get("limit_error"),
               "capped": capped, "cost_usd": (summary or {}).get("cost_usd"),
               "model_used": (summary or {}).get("model_used"),
               "attempts": (summary or {}).get("attempts"),
               "spend": round(month_spend(), 2), "budget": round(monthly_budget(), 2)}
        if s3_enabled():
            out["s3_ok"], out["s3_msg"] = push_story_to_s3(path)
        return out
    return {"ok": False, "errors": ["The model could not produce any usable story (try again, or check your API key)."]}


def _show_push_status(res):
    if "s3_ok" in res:
        if res["s3_ok"]:
            st.caption(f"☁️ Saved to cloud storage — {res.get('s3_msg', '')}")
        else:
            st.warning(f"Story saved locally, but **cloud upload failed**: {res.get('s3_msg', 'unknown error')}")
    if "pushed" not in res:
        return
    if res["pushed"]:
        st.caption("✅ Pushed to the git remote.")
    else:
        st.warning(f"Story saved, but **not pushed to git**: {res.get('push_msg', 'unknown error')}")
        st.caption("Headless server? Set `QUEST_GIT_TOKEN` (a GitHub PAT) in the environment / `.env`; "
                   "identity can be set with `QUEST_GIT_NAME` / `QUEST_GIT_EMAIL`.")


def show_create_page():
    if st.button("←  Back to library"):
        st.session_state.screen = "library"
        st.session_state.pop("gen_result", None)
        st.rerun()
    st.markdown("<h1>✨ Forge a New Story</h1>", unsafe_allow_html=True)

    res = st.session_state.get("gen_result")
    if res is not None:
        if res.get("capped_blocked"):
            st.error("✨ New-story creation is paused — this month's generation budget "
                     f"(${res.get('budget', '?')}) is used up and no free backup key is "
                     "configured. You can still play every story in the library.")
            if st.button("📚  Back to library", use_container_width=True):
                st.session_state.screen = "library"
                st.session_state.pop("gen_result", None)
                st.rerun()
            return
        if res.get("ok"):
            st.success(f"Created **“{res['title']}”** — saved to `{res['path']}`.")
            st.caption("Passed every gate: validate ✓ · coherence ✓ · balance PASS")
            if res.get("capped"):
                st.info("Made with the **free model** — this month's premium budget is used up.")
            if res.get("cost_usd") is not None:
                st.caption(f"💸 cost ≈ ${res['cost_usd']:.4f} · {res.get('attempts', '?')} model "
                           f"call(s) · month-to-date ${res.get('spend', '?')}/{res.get('budget', '?')}")
            _show_push_status(res)
            for ln in res.get("vlines", []):
                st.caption(f"· {ln}")
            c1, c2 = st.columns(2)
            if c1.button("▶  Play it now", use_container_width=True):
                select_story(res["path"])
                st.rerun()
            if c2.button("✨  Create another", use_container_width=True):
                st.session_state.pop("gen_result", None)
                st.rerun()
        elif res.get("draft"):
            st.warning(f"Saved **“{res['title']}”** as a **draft** — it didn't fully pass: "
                       + (", ".join(res.get("reasons", [])) or "some gates") + ".")
            if res.get("limit"):
                st.caption(f"A model limit was hit mid-run ({str(res['limit'])[:100]}…), so it stopped early.")
            st.caption("It's in your library marked **DRAFT** — playable now, or regenerate later for a clean version.")
            if res.get("capped"):
                st.info("Made with the **free model** — this month's premium budget is used up.")
            if res.get("cost_usd") is not None:
                st.caption(f"💸 cost ≈ ${res['cost_usd']:.4f} · {res.get('attempts', '?')} model "
                           f"call(s) · month-to-date ${res.get('spend', '?')}/{res.get('budget', '?')}")
            _show_push_status(res)
            for ln in res.get("vlines", []):
                st.caption(f"· {ln}")
            c1, c2 = st.columns(2)
            if c1.button("▶  Play the draft", use_container_width=True):
                select_story(res["path"])
                st.rerun()
            if c2.button("✨  Try again", use_container_width=True):
                st.session_state.pop("gen_result", None)
                st.rerun()
        else:
            st.error("Couldn't generate a usable story. Try again, or tweak the theme.")
            for e in res.get("errors", [])[:12]:
                st.caption(f"· {e}")
            if st.button("↩  Try again", use_container_width=True):
                st.session_state.pop("gen_result", None)
                st.rerun()
        return

    st.markdown(
        "<div style='background:#141008;border-left:3px solid #8b6914;border-radius:0 6px 6px 0;"
        "padding:1rem 1.3rem;margin:0.4rem 0 1rem;color:#c8b49a;font-size:0.9rem;line-height:1.6'>"
        "Describe a setting and pick a difficulty. The model writes a full branching adventure, then "
        "it must pass the validate → coherence → balance gates (auto-repairing on failure) before it's "
        "added to your library — so every story is consistent, well-connected, and ready to play."
        "</div>", unsafe_allow_html=True)

    if monthly_budget() > 0:
        if budget_exceeded():
            st.warning("This month's premium story budget is used up — new stories are created "
                       "with the **free model** (it may be slower or occasionally unavailable). "
                       "You can always play any story in the library.")
        else:
            st.caption(f"Story-generation budget this month: ${month_spend():.2f} / "
                       f"${monthly_budget():.2f} used.")

    theme = st.text_input("Theme / setting",
                          placeholder="e.g. Pirate ghost ship · Cyberpunk heist · Norse myth · Haunted Mars colony")
    c1, c2 = st.columns([2, 3])
    difficulty = c1.radio("Difficulty", DIFFICULTIES, index=1)
    length = c2.slider("Approx. number of locations", 8, 20, 14)
    title_hint = st.text_input("Title (optional)", placeholder="Leave blank to let the model name it")

    c3, c4 = st.columns([2, 3])
    language = c3.text_input("Language", value="English",
                             help="The language ALL story text is written in.")
    _levels = ["A1 — beginner", "A2 — elementary", "B1 — intermediate",
               "B2 — upper-intermediate", "C1 — advanced", "C2 — native"]
    language_level = c4.select_slider(
        "Language level (CEFR)", options=_levels, value=_levels[-1],
        help="Pick a lower level for language learning: simpler words, shorter sentences.",
    ).split(" ")[0]

    # Generation always uses the site owner's configured key (environment / Streamlit secrets).
    # Users are NEVER asked for their own API key. Provider and model are owner-controlled via
    # env: QUEST_GEN_PROVIDER (google|anthropic), QUEST_GEN_MODEL / QUEST_GEN_MODELS.
    provider = gen_provider()
    model    = gen_default_model(provider)
    api_key  = env_api_key(provider)

    if not api_key:
        st.info("✨ Story generation is currently unavailable — the site owner hasn't configured "
                "a generation key yet. You can still play every story in the library.")

    if st.button("✨  Generate Story", use_container_width=True,
                 disabled=not theme.strip() or not api_key):
        with st.spinner("Summoning a new world… the model writes it, then it must pass the "
                        "validate → coherence → balance gates (auto-repairing). This can take "
                        "a couple of minutes."):
            st.session_state.gen_result = _do_generate(
                theme.strip(), difficulty, length, title_hint.strip(), api_key, provider,
                model, language.strip() or "English", language_level)
        st.rerun()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    # one-time per session: pull stories from cloud storage so every machine sees the
    # same library (QUEST_S3_BUCKET — see story_engine.py)
    if s3_enabled() and not st.session_state.get("s3_synced"):
        st.session_state.s3_synced = True
        n, errs = sync_stories_from_s3()
        st.session_state.s3_sync_info = (n, errs)

    screen = st.session_state.get("screen", "library")

    if screen == "create":
        show_create_page()
        return

    if "active_story" not in st.session_state:
        show_library()
        return

    story = st.session_state.active_story

    if not st.session_state.get("char_creation_done"):
        show_char_creation(story)
        return

    # ── sidebar ───────────────────────────────────────────────────────────────
    render_inventory(story)
    st.sidebar.divider()
    if story.get("goal"):
        st.sidebar.markdown("**🎯 Goal**")
        st.sidebar.caption(story["goal"])
    if st.sidebar.button("📚  Story Library", use_container_width=True, key="side_lib"):
        go_to_library()
        st.rerun()
    st.sidebar.markdown(
        f"<div style='text-align:center;margin-top:0.5rem'>"
        f"<a href='{KOFI_URL}' target='_blank' style='color:#9a8a6a;font-size:0.8rem;"
        f"font-family:monospace;text-decoration:none'>☕ Support on Ko-fi</a></div>",
        unsafe_allow_html=True,
    )

    # ── guard: hp ─────────────────────────────────────────────────────────────
    if st.session_state.hp <= 0:
        st.session_state.game_over = True

    st.markdown(f"<h1>{story['title']}</h1>", unsafe_allow_html=True)
    st.caption(f"🌍 {story['theme']}")

    if st.session_state.game_over:
        st.error("💀  GAME OVER — Your journey ends in the dust.")
        show_end_buttons(story)
        return

    # ── guard: broken story link (no crash) ───────────────────────────────────
    loc_key = st.session_state.current_loc
    if loc_key not in st.session_state.locations:
        st.error(
            f"⚠ Broken story link: location '{loc_key}' does not exist. "
            f"This is a story-data bug — run the validator on this story's file in stories/."
        )
        show_end_buttons(story)
        return

    curr_loc = st.session_state.locations[loc_key]
    max_hp   = st.session_state.get("max_hp", story["character_template"]["health"])

    # apply location loot on first visit
    apply_loot(story, curr_loc)

    # ── stat bar ──────────────────────────────────────────────────────────────
    cols = st.columns(4)
    cols[0].metric("❤️ HP",  f"{st.session_state.hp}/{max_hp}")
    cols[1].metric("💪 STR", st.session_state.attributes["strength"])
    cols[2].metric("🏃 AGI", st.session_state.attributes["agility"])
    cols[3].metric("🫁 STA", st.session_state.attributes["stamina"])

    st.divider()

    # ── location description ──────────────────────────────────────────────────
    st.markdown(
        f"<div style='background:linear-gradient(135deg,#141008 0%,#0f0c06 100%);"
        f"border-left:3px solid #8b6914;border-radius:0 6px 6px 0;"
        f"padding:1.4rem 1.8rem;margin:0.5rem 0 1rem 0;"
        f"font-family:\"Special Elite\",Georgia,serif;"
        f"font-size:1.05rem;line-height:1.9;color:#d4c5a9;"
        f"box-shadow:inset 0 0 30px rgba(0,0,0,0.4)'>"
        f"{curr_loc['description']}</div>",
        unsafe_allow_html=True,
    )

    # ── event log ─────────────────────────────────────────────────────────────
    if st.session_state.log:
        with st.expander("📜  Event Log", expanded=False):
            for entry in reversed(st.session_state.log[-8:]):
                st.markdown(
                    f"<div style='color:#7a6a4a;font-size:0.83rem;"
                    f"font-family:monospace;padding:3px 0;"
                    f"border-bottom:1px solid #1e1a10'>{entry}</div>",
                    unsafe_allow_html=True,
                )

    # ── pending dice roll ─────────────────────────────────────────────────────
    pending        = st.session_state.get("pending_choice")
    pending_combat = st.session_state.get("pending_combat", False)

    if pending or pending_combat:
        if pending:
            cond  = pending.get("condition", {})
            attr  = cond.get("attribute", "strength")
            dc    = cond.get("check_value", 0)
            fail  = cond.get("fail_damage", 2)
            dice  = cond.get("dice_type", "1d6")
            bonus, bonus_item = _item_bonus(cond)
            attr_val = st.session_state.attributes.get(attr, 0)
            odds  = odds_label(dice, dc, attr_val, bonus)
            extra = f" +{bonus} {item_name(story, bonus_item)}" if bonus else ""
            label = (
                f"**{attr.upper()} check** — beat DC **{dc}** "
                f"(you roll {dice}{extra}+{attr_val}) · **{odds}** · *fail costs {fail} HP*"
            )
        else:
            monster = curr_loc["monster"]
            attr    = monster.get("attribute", "strength")
            dc      = monster["strength"]
            fail    = monster.get("fail_damage", 4)
            dice    = monster.get("dice_type", "1d6")
            attr_val = st.session_state.attributes.get(attr, 0)
            odds    = odds_label(dice, dc, attr_val)
            label   = (
                f"**{attr.upper()} check** — beat DC **{dc}** "
                f"· **{odds}** · *fail costs {fail} HP*"
            )

        st.markdown(
            f"<div style='background:#0c0a07;border:1px solid #3a2e14;"
            f"border-radius:6px;padding:1.2rem 1rem;margin:0.8rem 0;text-align:center'>"
            f"<div style='color:#7a6a4a;font-size:0.85rem;font-family:monospace;"
            f"margin-bottom:0.5rem'>{label}</div>"
            f"<div style='font-size:4rem'>🎲</div></div>",
            unsafe_allow_html=True,
        )

        if st.button("🎲  Throw the Dice!", use_container_width=True):
            if pending:
                resolve_choice(pending, story)
                st.session_state.pending_choice = None
            else:
                resolve_combat(curr_loc["monster"], st.session_state.current_loc, story)
                st.session_state.pending_combat = False
            st.rerun()

        if st.button("↩  Cancel", use_container_width=True):
            st.session_state.pending_choice = None
            st.session_state.pending_combat = False
            st.rerun()
        return

    # ── monster encounter ─────────────────────────────────────────────────────
    if "monster" in curr_loc:
        monster = curr_loc["monster"]
        m_attr  = monster.get("attribute", "strength")
        m_dice  = monster.get("dice_type", "1d6")
        attr_val = st.session_state.attributes.get(m_attr, 0)
        odds = odds_label(m_dice, monster["strength"], attr_val)
        st.error(f"⚔️  **{monster['name']}** blocks your path!")
        c1, c2, c3 = st.columns(3)
        c1.metric("Your HP",          f"{st.session_state.hp}/{max_hp}")
        c2.metric(f"Enemy {m_attr.upper()} DC", monster["strength"])
        c3.metric("Your odds",        odds)
        st.caption(f"Failure costs **{monster.get('fail_damage', 4)} HP**. You may retry.")

        if st.button(f"⚔️  Fight {monster['name']}", use_container_width=True):
            st.session_state.pending_combat = True
            st.rerun()

        flee = [c for c in curr_loc.get("choices", []) if c.get("is_flee")]
        if flee:
            st.caption("*Or flee:*")
            for c in flee:
                lbl = c["text"]
                if "condition" in c:
                    cc = c["condition"]
                    fa = st.session_state.attributes.get(cc["attribute"], 0)
                    b, _bi = _item_bonus(cc)
                    lbl += (f"  [{cc['attribute'].upper()} DC {cc['check_value']} · "
                            f"{odds_label(cc.get('dice_type','1d6'), cc['check_value'], fa, b)}]")
                if st.button(lbl, key=f"flee_{c['text']}"):
                    if "condition" in c:
                        st.session_state.pending_choice = c
                    else:
                        apply_choice_target(c, story)
                    st.rerun()
        return

    # ── ending ────────────────────────────────────────────────────────────────
    if curr_loc.get("is_end"):
        if curr_loc.get("is_victory", True):
            st.balloons()
            st.success("🎉  **VICTORY!** Your journey is complete.")
        else:
            st.error("💀  Your story ends here.")
        show_end_buttons(story)
        return

    # ── choices ───────────────────────────────────────────────────────────────
    st.markdown(
        "<div style='color:#6a5a3a;font-size:0.82rem;font-family:monospace;"
        "letter-spacing:1px;margin:0.5rem 0 0.3rem 0'>WHAT DO YOU DO?</div>",
        unsafe_allow_html=True,
    )

    inventory = st.session_state.get("inventory", [])
    items_def = story.get("items", {})

    for choice in curr_loc.get("choices", []):
        if choice.get("is_flee"):
            continue

        req = choice.get("requires_item")
        if req and req not in inventory:
            continue

        lbl = choice["text"]

        if "condition" in choice:
            cond = choice["condition"]
            attr_val = st.session_state.attributes.get(cond["attribute"], 0)
            bonus, bonus_item = _item_bonus(cond)
            odds = odds_label(cond.get("dice_type", "1d6"), cond["check_value"], attr_val, bonus)
            lbl += (
                f"\n  ↳ {cond['attribute'].upper()} check, "
                f"DC {cond['check_value']} · {odds}"
                + (f", fail −{cond['fail_damage']} HP" if cond.get("fail_damage") else "")
                + (f"  (+{bonus} {items_def.get(bonus_item, {}).get('name', bonus_item)})" if bonus else "")
            )

        given = _coerce_list(choice.get("gives_item"))
        if given:
            names = [f"{items_def.get(i, {}).get('icon','📦')} {items_def.get(i, {}).get('name', i)}" for i in given]
            lbl += f"\n  ↳ Receive: {', '.join(names)}"

        if choice.get("heals"):
            lbl += f"\n  ↳ Restores {choice['heals']} HP"

        if req:
            lbl += f"  [requires {items_def.get(req, {}).get('icon','📦')} {items_def.get(req, {}).get('name', req)}]"

        if st.button(lbl, key=choice["text"]):
            if "condition" in choice:
                st.session_state.pending_choice = choice
            else:
                apply_choice_target(choice, story)
            st.rerun()


if __name__ == "__main__":
    main()
