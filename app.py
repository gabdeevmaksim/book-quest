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

/* Form submit buttons (feedback "Send") — same look as the regular buttons */
[data-testid="stFormSubmitButton"] > button {
    background-color: #161208 !important;
    color: #b8a07a !important;
    border: 1px solid #3a2e14 !important;
    border-radius: 3px !important;
    font-family: 'Share Tech Mono', 'Courier New', monospace !important;
    font-size: 0.88rem !important;
    min-height: 2.6em !important;
}
[data-testid="stFormSubmitButton"] > button:hover {
    background-color: #201a0c !important;
    border-color: #d4a843 !important;
    color: #f0d890 !important;
}

/* Popover buttons (Share) + their dropdown — match the dark buttons instead of Streamlit's white */
[data-testid="stPopoverButton"] {
    background-color: #161208 !important;
    color: #b8a07a !important;
    border: 1px solid #3a2e14 !important;
    border-radius: 3px !important;
    font-family: 'Share Tech Mono', 'Courier New', monospace !important;
    font-size: 0.85rem !important;
    min-height: 2.8em !important;
    padding: 0.7em 0.5em !important;
    justify-content: center !important;
    box-shadow: none !important;
    transition: all 0.12s ease !important;
}
[data-testid="stPopoverButton"]:hover {
    background-color: #201a0c !important;
    border-color: #d4a843 !important;
    color: #f0d890 !important;
}
[data-testid="stPopoverButton"] * { color: inherit !important; }
[data-testid="stPopoverBody"] {
    background-color: #141008 !important;
    border: 1px solid #3a2e14 !important;
}
[data-testid="stPopoverBody"] [data-testid="stCode"] pre,
[data-testid="stPopoverBody"] [data-testid="stCode"] code {
    background-color: #0c0a07 !important;
    color: #c8b49a !important;
}
[data-testid="stPopoverBody"] [data-testid="stCode"] pre { border: 1px solid #2a2010 !important; }

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

# Support / donations
KOFI_URL     = "https://ko-fi.com/dedulek"
SPONSORS_URL = "https://github.com/sponsors/gabdeevmaksim"

from story_engine import (  # Streamlit-free core (shared with story_agent.py)
    DIFFICULTIES, PROVIDER_LABEL, PROVIDER_PKG,
    gen_provider, gen_default_model, env_api_key,
    list_stories, load_story_file, unique_story_path, save_story_file,
    validate_story_dict, balance_check, generate_story_api,
    gen_models, create_story,
    s3_enabled, push_story_to_s3, sync_stories_from_s3,
    monthly_budget, month_spend, budget_exceeded, record_spend, budget_fallback_models,
    budget_left, review_models, free_tier, money,
)
import contextlib
import urllib.parse

import visits     # visit / unique-visitor counter (SQLite in state/, salted hashes only)
import feedback   # player feedback: file + Telegram (Streamlit-free, see feedback.py)
import quota as Q  # Gemini free-tier limits: per-model counters, capacity, one-at-a-time slot
import hashlib
import uuid


def client_ip():
    """The visitor's IP address if Streamlit exposes it (never stored as-is), else None."""
    ctx = getattr(st, "context", None)
    try:
        ip = getattr(ctx, "ip_address", None) or \
            ((ctx.headers.get("X-Forwarded-For") or "").split(",")[0].strip() if ctx else None)
    except Exception:
        ip = None
    return ip if isinstance(ip, str) and ip else None


def player_id():
    """Anonymous per-player key for the daily story cap: a short hash of the IP address when
    Streamlit exposes it, else a per-browser-session id (kept across navigation)."""
    ip = client_ip()
    if ip:
        return "ip:" + hashlib.sha256(ip.encode()).hexdigest()[:16]
    if not st.session_state.get("fbmeta_player"):
        st.session_state["fbmeta_player"] = uuid.uuid4().hex[:16]
    return "s:" + st.session_state["fbmeta_player"]
import game_rules as R   # challenge mechanics, shared with playtest.py (see game_rules.py)


# ── sharing & deep links ──────────────────────────────────────────────────────
# Public base URL used in share links. Set QUEST_PUBLIC_URL (e.g. https://play.yourdomain)
# once you have a domain; until then it falls back to the droplet's address.
PUBLIC_URL = (os.environ.get("QUEST_PUBLIC_URL") or "http://134.122.120.45").rstrip("/")

SHARE_TARGETS = [
    ("Telegram", "https://t.me/share/url?url={u}&text={t}"),
    ("WhatsApp", "https://wa.me/?text={t}%20{u}"),
    ("X",        "https://x.com/intent/tweet?text={t}&url={u}"),
]


def story_slug(path):
    """Library key for a story: its filename without .json (used in ?story= links)."""
    return os.path.splitext(os.path.basename(path or ""))[0]


def story_url(path):
    return f"{PUBLIC_URL}/?story={urllib.parse.quote(story_slug(path))}"


def find_story_by_slug(slug):
    """Resolve ?story=<slug> to a library path. Only matches files that are actually in
    the library, so a crafted link can never reach anything outside stories/."""
    for s in list_stories():
        if not s.get("error") and story_slug(s["path"]) == slug:
            return s["path"]
    return None


def share_links_html(text, url):
    q = lambda v: urllib.parse.quote(v, safe="")
    t, u = q(text), q(url)
    links = " · ".join(
        f"<a href='{tpl.format(u=u, t=t)}' target='_blank' rel='noopener' "
        f"style='color:#d4a843;text-decoration:none'>{name}</a>"
        for name, tpl in SHARE_TARGETS)
    return (f"<div style='font-family:monospace;font-size:0.88rem;margin:0.2rem 0 0.6rem'>"
            f"{links}</div>")


def render_share(text, url, label="Share"):
    """Share menu: one-click links to Telegram, WhatsApp, X + a copyable link."""
    box = (st.popover(label, use_container_width=True) if hasattr(st, "popover")
           else st.expander(label))
    with box:
        st.markdown(share_links_html(text, url), unsafe_allow_html=True)
        st.caption("Or copy the link:")
        st.code(url, language=None)


def render_result_share(story, victory):
    """Share button for the end screen, with the player's result in the message."""
    title = story.get("title", "Quest Book")
    path = st.session_state.get("active_story_path")
    if victory:
        hp, mx = max(st.session_state.get("hp", 0), 0), st.session_state.get("max_hp", 0)
        text = f"I conquered “{title}” on Quest Book with {hp}/{mx} HP left! Can you do better?"
    else:
        text = f"I met my end in “{title}” on Quest Book… Think you can survive it?"
    render_share(text, story_url(path) if path else PUBLIC_URL, label="Share your result")


# ── feedback ──────────────────────────────────────────────────────────────────
# Submissions are saved to state/feedback.jsonl and sent to the owner's Telegram
# (see feedback.py). Context (story, location, HP, outcome) is attached automatically.
FB_KINDS    = {"bug": "Bug", "story": "Story", "idea": "Idea", "other": "Other"}
FB_STARS    = ["★", "★★", "★★★", "★★★★", "★★★★★"]
FB_COOLDOWN = 60       # seconds between submissions per session
FB_MAX      = 5        # submissions per session
# Session keys with this prefix survive navigation (library / restart / new story), so the
# cooldown and "already rated" flags can't be reset just by going back to the library.
FB_KEEP_PREFIX = "fbmeta_"


@lru_cache(maxsize=1)
def app_version():
    """Short git hash of the running code (shown in feedback so bugs map to a version)."""
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return ""


def clear_session():
    """Reset session state for a new screen/run, keeping the feedback anti-spam bookkeeping."""
    for k in list(st.session_state.keys()):
        if not str(k).startswith(FB_KEEP_PREFIX):
            del st.session_state[k]


def feedback_context():
    """Game context attached to every submission so reports are reproducible."""
    ss = st.session_state
    ctx = {"screen": ss.get("screen", "library"), "version": app_version()}
    story = ss.get("active_story")
    if story:
        ctx.update(story=story.get("title", ""), slug=story_slug(ss.get("active_story_path")),
                   difficulty=story.get("difficulty", ""),
                   language=story.get("language") or "English")
        if ss.get("char_creation_done"):
            loc = ss.get("current_loc")
            node = (ss.get("locations") or {}).get(loc, {})
            if ss.get("game_over") or ss.get("hp", 1) <= 0:
                outcome = "defeat"
            elif node.get("is_end"):
                outcome = "victory" if node.get("is_victory", True) else "bad ending"
            else:
                outcome = "playing"
            ctx.update(location=loc, hp=f"{ss.get('hp')}/{ss.get('max_hp')}", outcome=outcome)
    return {k: v for k, v in ctx.items() if v not in (None, "")}


def _feedback_blocked():
    ss = st.session_state
    if ss.get("fbmeta_count", 0) >= FB_MAX:
        return "Thanks — you've already sent plenty of feedback this session!"
    wait = FB_COOLDOWN - (time.time() - ss.get("fbmeta_last", 0))
    if wait > 0:
        return f"Please wait {int(wait) + 1} s before sending more feedback."
    return None


def send_feedback(kind, message, rating=None, contact=""):
    """Validate, rate-limit and submit. Returns (ok, note) for the UI."""
    if not (message or "").strip() and not rating:
        return False, "Write a message or pick a rating first."
    blocked = _feedback_blocked()
    if blocked:
        return False, blocked
    res = feedback.submit(kind, message, rating, contact, feedback_context())
    if not res["saved"]:
        return False, "Sorry — your feedback couldn't be saved right now. Please try again later."
    st.session_state.fbmeta_count = st.session_state.get("fbmeta_count", 0) + 1
    st.session_state.fbmeta_last = time.time()
    return True, "Thank you! Your feedback reached the author."


def render_feedback(where, label="Send feedback"):
    """Feedback popover: kind, optional star rating, message, optional contact."""
    with st.popover(label, use_container_width=True):
        with st.form(f"fb_form_{where}", clear_on_submit=True, border=False):
            kind = st.radio("What is it about?", list(FB_KINDS), format_func=FB_KINDS.get,
                            horizontal=True, key=f"fb_kind_{where}")
            stars = st.radio("Rating (optional)", FB_STARS, index=None, horizontal=True,
                             key=f"fb_rate_{where}")
            message = st.text_area("Message", max_chars=feedback.MAX_MESSAGE,
                                   key=f"fb_msg_{where}",
                                   placeholder="A bug, a story you loved or hated, an idea…")
            contact = st.text_input("Contact (optional)", max_chars=feedback.MAX_CONTACT,
                                    key=f"fb_contact_{where}",
                                    placeholder="Email or Telegram, if you'd like a reply")
            sent = st.form_submit_button("Send", use_container_width=True)
        if sent:
            ok, note = send_feedback(kind, message, len(stars) if stars else None, contact)
            (st.success if ok else st.warning)(note)
            if ok:
                st.toast(note)
        st.caption("Your current story, location and HP are attached automatically.")


def render_rate_story(story):
    """End-screen 'How did you like this story?' — once per story per session."""
    slug = story_slug(st.session_state.get("active_story_path")) or story.get("title", "story")
    flag = f"{FB_KEEP_PREFIX}rated_{slug}"
    if st.session_state.get(flag):
        st.caption("★ Thanks for rating this story!")
        return
    with st.form("fb_form_end", clear_on_submit=True):
        st.markdown("**How did you like this story?**")
        stars = st.radio("Rating", FB_STARS, index=None, horizontal=True, key="fb_rate_end",
                         label_visibility="collapsed")
        comment = st.text_input("Comment (optional)", max_chars=feedback.MAX_MESSAGE,
                                key="fb_msg_end", placeholder="What worked, what didn't?")
        sent = st.form_submit_button("Send rating", use_container_width=True)
    if sent:
        if not stars:
            st.warning("Pick 1–5 stars first.")
        else:
            ok, note = send_feedback("story", comment, len(stars))
            if ok:
                st.session_state[flag] = True
                st.success("★ Thanks for rating this story!")
            else:
                st.warning(note)


# ── dice & text helpers ───────────────────────────────────────────────────────


def roll_dice(dice_type="1d6"):
    return R.roll_dice(dice_type)


def pass_probability(dice_type, need):
    """P(dice roll >= need). need = check_value - attribute - bonuses."""
    return R.pass_probability(dice_type, need)


def odds_label(dice_type, check_value, attr_val, bonus=0):
    p = pass_probability(dice_type, check_value - attr_val - bonus)
    if p >= 1:
        return "✓ sure, no roll"
    return f"≈{min(99, round(p * 100))}%"


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
    clear_session()
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
        st.session_state.history            = []
        st.session_state.last_outcome       = None


def move_to(target):
    """Move the hero, remembering where they came from (for easy-mode Go Back)."""
    st.session_state.setdefault("history", []).append(st.session_state.current_loc)
    st.session_state.current_loc = target


def take_choice(choice, story):
    """A choice button was clicked: checks wait for the dice, everything else moves at once."""
    st.session_state.last_outcome = None
    if "condition" in choice:
        if R.check_is_sure(choice["condition"], st.session_state.attributes,
                           st.session_state.get("inventory", [])):
            resolve_choice(choice, story)        # strong enough: straight through, no dice
        else:
            st.session_state.pending_choice = choice
    else:
        apply_choice_target(choice, story)


def apply_choice_target(choice, story):
    move_to(choice["target_id"])
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

def _record_outcome(res, story):
    """Apply a resolved challenge: lose HP on failure, log it, and keep it for the outcome card."""
    st.session_state.hp -= res["damage"]
    bonus_txt = f"+{res['bonus']}({item_name(story, res['bonus_item'])})" if res["bonus"] else ""
    if res.get("auto"):
        math = f"{res['attribute'].upper()} {res['attr_value']}{bonus_txt} vs DC {res['dc']} — no roll needed"
    else:
        math = f"{res['roll']}+{res['attr_value']}{bonus_txt}={res['total']} vs DC {res['dc']}"
    hurt = f" · −{res['damage']} HP" if res["damage"] else ""
    if res["kind"] == "monster":
        verb = "beaten" if res["passed"] else "you got past, wounded"
        st.session_state.log.append(f"{'⚔️' if res['passed'] else '💥'} {res['name']} — {verb}. {math}{hurt}")
    else:
        verb = "passed" if res["passed"] else "failed, but you got through"
        st.session_state.log.append(
            f"{'✅' if res['passed'] else '❌'} {res['attribute'].upper()} check {verb}. {math}{hurt}")
    st.session_state.last_outcome = res
    if st.session_state.hp <= 0:
        st.session_state.game_over = True


def resolve_choice(choice, story):
    """Roll for a checked choice. Win or lose, the hero moves on — failure just costs HP."""
    if "condition" not in choice:
        apply_choice_target(choice, story)
        return
    cond = choice["condition"]
    sure = R.check_is_sure(cond, st.session_state.attributes, st.session_state.get("inventory", []))
    roll = None if sure else animate_roll(st.empty(), cond.get("dice_type", R.DEFAULT_DICE))
    res = R.resolve_check(cond, st.session_state.attributes,
                          st.session_state.get("inventory", []), roll=roll)
    _record_outcome(res, story)
    if st.session_state.game_over:
        return
    dest, legacy = R.check_destination(choice, res["passed"])
    if legacy:
        move_to(dest)            # older story: failure still routed to its old fail_target
    else:
        apply_choice_target(choice, story)


def resolve_combat(monster, loc_id, story):
    """One roll decides the whole encounter; either way it's over and the path opens."""
    sure = R.monster_is_sure(monster, st.session_state.attributes)
    roll = None if sure else animate_roll(st.empty(), monster.get("dice_type", R.DEFAULT_DICE))
    res = R.resolve_monster(monster, st.session_state.attributes, roll=roll)
    _record_outcome(res, story)
    st.session_state.locations[loc_id].pop("monster", None)


def render_outcome():
    """Card showing what just happened on the last roll (success or the injury taken)."""
    o = st.session_state.get("last_outcome")
    if not o:
        return
    ok = o["passed"]
    accent = "#6f9a52" if ok else "#b0563f"
    if o["kind"] == "monster":
        head = f"⚔️ {o['name']} — {'beaten' if ok else 'you got past, wounded'}"
    else:
        head = f"{'✅' if ok else '❌'} {o['attribute'].upper()} check {'passed' if ok else 'failed'}"
    if o.get("auto"):
        head += f" · your {o['attribute'].upper()} {o['attr_value']} was enough — no roll needed"
    else:
        head += f" · {o['total']} vs DC {o['dc']}" + ("" if ok else f" · −{o['damage']} HP")
    st.markdown(
        f"<div style='background:#100d08;border:1px solid #2a2418;border-left:3px solid {accent};"
        f"border-radius:0 6px 6px 0;padding:0.8rem 1.2rem;margin:0.4rem 0 0.8rem 0'>"
        f"<div style='color:{accent};font-family:\"Share Tech Mono\",monospace;font-size:0.8rem;"
        f"letter-spacing:0.5px;margin-bottom:0.35rem'>{head}</div>"
        f"<div style='color:#d4c5a9;font-family:\"Special Elite\",Georgia,serif;font-size:0.98rem;"
        f"line-height:1.7'>{o['text']}</div></div>",
        unsafe_allow_html=True,
    )


def render_go_back(story):
    """Easy mode only: retrace your steps (items stay taken, beaten monsters stay beaten)."""
    if (story.get("difficulty") or "").lower() != "easy" or not st.session_state.get("history"):
        return
    if st.button("↩  Go back", use_container_width=True, key="go_back",
                 help="Easy mode: return to the previous place and choose another path."):
        st.session_state.current_loc = st.session_state.history.pop()
        st.session_state.last_outcome = None
        st.session_state.log.append("↩ You retrace your steps.")
        st.rerun()


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
        st.session_state.history            = []
        st.session_state.last_outcome       = None
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
    clear_session()
    st.session_state.screen = "library"
    st.query_params.clear()          # drop ?story= so the library URL stays clean


def select_story(path):
    """Make `path` the active story and begin a fresh run (character creation)."""
    story = load_story_file(path)
    clear_session()
    st.session_state.active_story      = story
    st.session_state.active_story_path = path
    st.session_state.screen            = "game"
    st.query_params["story"] = story_slug(path)   # the address bar is now a shareable link


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

    missing = st.session_state.pop("deep_link_missing", None)
    if missing:
        st.warning(f"The shared story “{missing}” isn't in the library — pick another adventure below.")

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
            c_play, c_share = st.columns([3, 1])
            if c_play.button("▶  Play", key=f"play_{s['path']}", use_container_width=True):
                select_story(s["path"])
                st.rerun()
            with c_share:
                render_share(f"Play “{s['title']}” — a free choose-your-own-adventure on Quest Book",
                             story_url(s["path"]), label="Share")

    st.divider()
    _btn = ("text-decoration:none;font-family:\"Share Tech Mono\",monospace;font-size:0.85rem;"
            "border:1px solid #3a2e14;border-radius:4px;padding:0.55rem 1.1rem;background:#161208")
    st.markdown(
        f"<div style='text-align:center;margin:0.3rem 0'>"
        f"<div style='color:#6a5a42;font-family:monospace;font-size:0.8rem;margin-bottom:0.7rem'>"
        f"Enjoying the quests? Help keep them free:</div>"
        f"<div style='display:flex;gap:0.6rem;justify-content:center;flex-wrap:wrap'>"
        f"<a href='{KOFI_URL}' target='_blank' rel='noopener' style='color:#d4a843;{_btn}'>"
        f"☕  Support on Ko-fi</a>"
        f"<a href='{SPONSORS_URL}' target='_blank' rel='noopener' style='color:#e58bbd;{_btn}'>"
        f"♥  Sponsor on GitHub</a></div></div>",
        unsafe_allow_html=True,
    )
    st.write("")
    _left, mid, _right = st.columns([1, 1, 1])
    with mid:
        render_feedback("library")
    render_visit_counter()


def _do_generate(theme, difficulty, length, title_hint, api_key, provider, model,
                 language="English", language_level="C2"):
    # Monthly budget policy: while under the cap, use the owner's chosen model first, with the
    # provider chain as automatic fallback. Once this month's spend reaches the cap, generation
    # moves to the FREE Google project (QUEST_GOOGLE_FREE_API_KEY — billing is per project, so
    # the paid key can't do it): free-tier limits, $0, one story at a time. Without a free key
    # creation pauses until next month — the library stays fully playable. create_story runs
    # the FULL gated pipeline (validate -> coherence -> balance -> review, with repair).
    capped = budget_exceeded()
    if capped:
        fallback = budget_fallback_models()
        if not fallback:
            return {"ok": False, "capped_blocked": True,
                    "spend": round(month_spend(), 2), "budget": round(monthly_budget(), 2)}
        provider, models = "google", fallback
    else:
        models = [model] + [m for m in gen_models(provider) if m != model]
    with (free_tier() if capped else contextlib.nullcontext()):
        if capped:
            api_key = env_api_key("google")      # the free project's key (inside free_tier)
        return _run_generation(theme, difficulty, length, title_hint, api_key, provider, models,
                               capped, language, language_level)


def _run_generation(theme, difficulty, length, title_hint, api_key, provider, models, capped,
                    language, language_level):
    # Free tier: one generation at a time (Flash models allow only 5 requests/minute), so
    # simultaneous players queue for up to ~2.5 min instead of tripping the per-minute limit.
    # Paid tier (1000/min): players generate in parallel.
    one_at_a_time = provider == "google" and Q.tier() == "free"
    slot = Q.generation_slot(timeout=150) if one_at_a_time else contextlib.nullcontext(True)
    with slot as got:
        if not got:
            return {"ok": False, "busy": True}
        Q.record_client(player_id())             # counts toward the per-player daily cap
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
            if "quota is used up" in str(e):
                return {"ok": False, "quota_out": True, "resets_in": Q.format_reset()}
            return {"ok": False, "errors": [f"Generation failed: {e}"]}

    # bank this generation's cost against the monthly budget (≈0 when on the free chain)
    if summary and summary.get("cost_usd") is not None:
        record_spend(summary.get("cost_usd", 0.0), summary.get("model_used", ""),
                     summary.get("tokens_in", 0), summary.get("tokens_out", 0))
    # Stories are kept on the server (stories/) and backed up to S3 — never pushed to git.
    if ok:
        title = load_story_file(path).get("title") or theme
        out = {"ok": True, "path": path, "title": title,
               "verdict": summary["balance"], "vlines": summary["bal_lines"], "gates": summary,
               "capped": capped, "cost_usd": summary.get("cost_usd"),
               "model_used": summary.get("model_used"), "attempts": summary.get("attempts"),
               "spend": round(month_spend(), 2), "budget": round(monthly_budget(), 2)}
        if s3_enabled():
            out["s3_ok"], out["s3_msg"] = push_story_to_s3(path)
        return out
    if path:   # gates not fully met / a model limit was hit — best draft was kept
        title = load_story_file(path).get("title") or theme
        reasons = []
        if summary and not summary.get("correctness"):
            reasons.append("valid links/reachability")
        if summary and not summary.get("coherence"):
            reasons.append("coherence (loops or thin opening)")
        if summary and summary.get("balance") != "PASS":
            reasons.append(f"balance ({summary.get('balance')}) for '{difficulty}'")
        if summary and summary.get("review") == "REVIEW":
            reasons.append("story continuity (the story review found problems)")
        out = {"ok": False, "draft": True, "path": path, "title": title, "reasons": reasons,
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
    """Where the new story is stored: always on the server; plus the S3 backup if enabled."""
    if "s3_ok" in res:
        if res["s3_ok"]:
            st.caption(f"☁️ Saved to cloud storage — {res.get('s3_msg', '')}")
        else:
            st.warning(f"Story saved locally, but **cloud upload failed**: {res.get('s3_msg', 'unknown error')}")


def show_create_page():
    if st.button("←  Back to library"):
        st.session_state.screen = "library"
        st.session_state.pop("gen_result", None)
        st.rerun()
    st.markdown("<h1>✨ Forge a New Story</h1>", unsafe_allow_html=True)

    res = st.session_state.get("gen_result")
    if res is not None:
        if res.get("busy") or res.get("quota_out"):
            if res.get("busy"):
                st.warning("Another story is being created right now — only one can be made at a "
                           "time. Please try again in a minute or two.")
            else:
                st.warning("Today's story-creation quota ran out while your story was being "
                           f"written. New stories can be created again in {res.get('resets_in')} "
                           "(midnight Pacific). You can still play every story in the library.")
            c1, c2 = st.columns(2)
            if c1.button("↩  Try again", use_container_width=True):
                st.session_state.pop("gen_result", None)
                st.rerun()
            if c2.button("📚  Back to library", use_container_width=True):
                st.session_state.screen = "library"
                st.session_state.pop("gen_result", None)
                st.rerun()
            return
        if res.get("capped_blocked"):
            st.error("✨ New-story creation is paused — this month's generation budget "
                     f"({money(res.get('budget'))}) is used up. It starts again next month. "
                     "You can still play every story in the library.")
            if st.button("📚  Back to library", use_container_width=True):
                st.session_state.screen = "library"
                st.session_state.pop("gen_result", None)
                st.rerun()
            return
        if res.get("ok"):
            st.success(f"Created **“{res['title']}”** — saved to `{res['path']}`.")
            _rv = (res.get("gates") or {}).get("review", "off")
            st.caption("Passed every gate: validate ✓ · coherence ✓ · balance PASS · story review "
                       + {"OK": "✓", "skipped": "skipped", "off": "off"}.get(_rv, str(_rv)))
            if res.get("capped"):
                st.info("Made on the **free tier** — this month's budget is used up, so stories "
                        "take longer and may be a little less polished until next month.")
            if res.get("cost_usd") is not None:
                st.caption(f"💸 cost ≈ {money(res['cost_usd'], 3)} · {res.get('attempts', '?')} model "
                           f"call(s)" + (f" · month-to-date {money(res.get('spend'))} / "
                                         f"{money(res.get('budget'))}" if res.get('budget') else ""))
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
                st.info("Made on the **free tier** — this month's budget is used up, so stories "
                        "take longer and may be a little less polished until next month.")
            if res.get("cost_usd") is not None:
                st.caption(f"💸 cost ≈ {money(res['cost_usd'], 3)} · {res.get('attempts', '?')} model "
                           f"call(s)" + (f" · month-to-date {money(res.get('spend'))} / "
                                         f"{money(res.get('budget'))}" if res.get('budget') else ""))
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
        "it must pass the validate → coherence → balance → story-review gates (auto-repairing on "
        "failure) before it's added to your library — so every story is consistent, well-connected, "
        "and ready to play."
        "</div>", unsafe_allow_html=True)

    # Budget state: under the cap → paid models; over it → the free tier (if a free key is
    # configured) or paused until next month.
    on_free_backup = budget_paused = False
    if monthly_budget() > 0 and budget_exceeded():
        if budget_fallback_models():
            on_free_backup = True
            st.info("🐢 This month's story budget is used up, so new stories are now written on the "
                    "**free tier** until next month: creating one **takes longer** (players take turns, "
                    "one story at a time) and the result **may be a little less polished**. "
                    "You can always play any story in the library.")
        else:
            budget_paused = True
            st.warning("✨ This month's story-creation budget is used up, so creating new stories "
                       "is paused until next month. You can still play every story in the library.")

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

    # capacity: how many more stories (daily request limits and, on a paid key, the money left
    # in this month's budget), and this player's daily share
    blocked = budget_paused
    if api_key and provider == "google" and not budget_paused:
        if on_free_backup:
            with free_tier():
                cap = Q.capacity(budget_fallback_models(), review_models(provider))
        else:
            # with a free backup the budget never blocks (the next story after the cap goes free)
            cap = Q.capacity(gen_models(provider), review_models(provider),
                             budget_left=None if budget_fallback_models() else budget_left())
        used, per_player = Q.client_used(player_id()), Q.stories_per_player()
        n, s = cap["stories"], "y" if cap["stories"] == 1 else "ies"
        if cap["limited_by"] == "budget":
            st.caption(f"🔋 About **{n}** new stor{s} left in this month's budget · "
                       f"you've made {used}/{per_player} today")
        else:
            st.caption(f"🔋 About **{n}** new stor{s} can still be created today · you've made "
                       f"{used}/{per_player} · resets in {cap['resets_in_text']} (midnight Pacific)")
        if n < 1:
            blocked = True
            if cap["limited_by"] == "budget":
                st.warning("This month's story-creation budget is almost used up, so creating new "
                           "stories is paused until next month. You can still play every story in "
                           "the library.")
            else:
                st.warning(f"Today's story-creation quota is used up — new stories can be created "
                           f"again in {cap['resets_in_text']}. You can still play every story in "
                           f"the library.")
        elif used >= per_player:
            blocked = True
            st.info(f"You've created {per_player} stories today — that's the daily limit per player, "
                    f"so everyone gets a turn. Come back in {cap['resets_in_text']}.")

    if st.button("✨  Generate Story", use_container_width=True,
                 disabled=not theme.strip() or not api_key or blocked):
        with st.spinner("Summoning a new world… the model writes it, then it must pass the "
                        "validate → coherence → balance → story-review gates (auto-repairing). "
                        "This can take a few minutes — and if someone else is creating a story "
                        "right now, you're next in line."):
            st.session_state.gen_result = _do_generate(
                theme.strip(), difficulty, length, title_hint.strip(), api_key, provider,
                model, language.strip() or "English", language_level)
        st.rerun()


# ── main ──────────────────────────────────────────────────────────────────────

def count_visit():
    """Once per browser session: +1 visit, and remember the (hashed) visitor for the day."""
    if st.session_state.get("fbmeta_visited"):         # fbmeta_* survives clear_session()
        return
    st.session_state["fbmeta_visited"] = True
    if not st.session_state.get("fbmeta_player"):
        st.session_state["fbmeta_player"] = uuid.uuid4().hex[:16]
    visits.record_visit(client_ip() or "s:" + st.session_state["fbmeta_player"])


def render_visit_counter():
    """Small public counter in the library footer (QUEST_SHOW_VISITS=0 hides it)."""
    if os.environ.get("QUEST_SHOW_VISITS", "1").strip() == "0":
        return
    t = visits.totals()
    if not t["visits"]:
        return
    st.markdown(
        f"<div style='text-align:center;color:#5a4c36;font-family:monospace;font-size:0.75rem;"
        f"margin-top:0.8rem'>👁 {t['visits']:,} visits · {t['visitors']:,} adventurers "
        f"· {t['visitors_today']:,} today</div>".replace(",", "\u202f"),
        unsafe_allow_html=True)


def main():
    count_visit()
    # one-time per session: pull stories from cloud storage so every machine sees the
    # same library (QUEST_S3_BUCKET — see story_engine.py)
    if s3_enabled() and not st.session_state.get("s3_synced"):
        st.session_state.s3_synced = True
        n, errs = sync_stories_from_s3()
        st.session_state.s3_sync_info = (n, errs)

    # deep link: ?story=<slug> opens that story straight away (shared links / bookmarks)
    wanted = st.query_params.get("story")
    if (wanted and st.session_state.get("screen") != "create"
            and st.session_state.get("active_story_path") is None):
        path = find_story_by_slug(wanted)
        if path:
            select_story(path)
        else:
            st.query_params.clear()
            st.session_state.deep_link_missing = wanted

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
    with st.sidebar:
        render_feedback("game")
    st.sidebar.markdown(
        f"<div style='text-align:center;margin-top:0.5rem'>"
        f"<span style='font-size:0.8rem;font-family:monospace'>"
        f"<a href='{KOFI_URL}' target='_blank' rel='noopener' "
        f"style='color:#9a8a6a;text-decoration:none'>☕ Ko-fi</a>"
        f"<span style='color:#4a3e2a'>  ·  </span>"
        f"<a href='{SPONSORS_URL}' target='_blank' rel='noopener' "
        f"style='color:#9a8a6a;text-decoration:none'>♥ GitHub Sponsors</a></span></div>",
        unsafe_allow_html=True,
    )

    # ── guard: hp ─────────────────────────────────────────────────────────────
    if st.session_state.hp <= 0:
        st.session_state.game_over = True

    st.markdown(f"<h1>{story['title']}</h1>", unsafe_allow_html=True)
    st.caption(f"🌍 {story['theme']}")

    if st.session_state.game_over:
        render_outcome()                      # the blow that ended the run
        st.error("💀  GAME OVER — Your journey ends in the dust.")
        render_result_share(story, victory=False)
        render_rate_story(story)
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

    # ── outcome of the last roll (what happened on the way here) ─────────────
    render_outcome()

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
                f"(you roll {dice}{extra}+{attr_val}) · **{odds}** · "
                f"*fail: you still get through, but lose {fail} HP*"
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
                f"**{attr.upper()} vs {monster['name']}** — beat DC **{dc}** "
                f"· **{odds}** · *lose: you still get past, but lose {fail} HP*"
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
        st.caption(f"One roll decides it: win and you're through cleanly — lose and you still get "
                   f"past, but it costs **{monster.get('fail_damage', R.DEFAULT_MONSTER_DAMAGE)} HP**.")

        if st.button(f"⚔️  Fight {monster['name']}", use_container_width=True):
            st.session_state.last_outcome = None
            if R.monster_is_sure(monster, st.session_state.attributes):
                resolve_combat(monster, st.session_state.current_loc, story)   # no dice needed
            else:
                st.session_state.pending_combat = True
            st.rerun()

        flee = [c for c in curr_loc.get("choices", []) if c.get("is_flee")]
        if flee:
            st.caption("*Or try another way:*")
            for c in flee:
                lbl = c["text"]
                if "condition" in c:
                    cc = c["condition"]
                    fa = st.session_state.attributes.get(cc["attribute"], 0)
                    b, _bi = _item_bonus(cc)
                    lbl += (f"  [{cc['attribute'].upper()} DC {cc['check_value']} · "
                            f"{odds_label(cc.get('dice_type','1d6'), cc['check_value'], fa, b)}]")
                if st.button(lbl, key=f"flee_{c['text']}"):
                    take_choice(c, story)
                    st.rerun()
        render_go_back(story)
        return

    # ── ending ────────────────────────────────────────────────────────────────
    if curr_loc.get("is_end"):
        if curr_loc.get("is_victory", True):
            if not st.session_state.get("celebrated"):     # once per run, not on every rerun
                st.balloons()
                st.session_state.celebrated = True
            st.success("🎉  **VICTORY!** Your journey is complete.")
        else:
            st.error("💀  Your story ends here.")
            render_go_back(story)                  # easy mode: undo the fatal decision
        render_result_share(story, victory=curr_loc.get("is_victory", True))
        render_rate_story(story)
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
                + (f", fail −{cond['fail_damage']} HP"
                   if cond.get("fail_damage") and not odds.startswith("✓") else "")
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
            take_choice(choice, story)
            st.rerun()

    render_go_back(story)


if __name__ == "__main__":
    main()
