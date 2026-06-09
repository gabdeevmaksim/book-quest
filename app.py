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

# ── story library / generation config ─────────────────────────────────────────
STORIES_DIR    = os.environ.get("QUEST_STORIES_DIR", "stories")
LEGACY_STORY   = os.environ.get("QUEST_STORY", "story.json")
VALIDATOR_PATH = os.path.join("cyoa-skills", "cyoa-validator", "scripts", "validate_story.py")
GENERATOR_SPEC = os.path.join("cyoa-skills", "cyoa-generator", "SKILL.md")
DIFFICULTIES   = ["easy", "normal", "hard"]
GEN_MAX_TOKENS = 16000

DEFAULT_MODELS = {"google": "gemini-3.5-flash", "anthropic": "claude-sonnet-4-6"}
PROVIDER_LABEL = {"google": "Google (Gemini)", "anthropic": "Anthropic (Claude)"}
PROVIDER_PKG   = {"google": "google-genai", "anthropic": "anthropic"}


def gen_provider():
    """Pick the model provider from env (QUEST_GEN_PROVIDER), else whichever API key is set."""
    p = os.environ.get("QUEST_GEN_PROVIDER", "").strip().lower()
    if p in ("google", "gemini"):
        return "google"
    if p in ("anthropic", "claude"):
        return "anthropic"
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return "google"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "google"


def gen_default_model(provider):
    return os.environ.get("QUEST_GEN_MODEL") or DEFAULT_MODELS.get(provider, "")


def env_api_key(provider):
    if provider == "google":
        return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""
    return os.environ.get("ANTHROPIC_API_KEY") or ""


def list_stories():
    """Metadata for every story in the library (always includes legacy story.json if present)."""
    paths = sorted(p for p in glob.glob(os.path.join(STORIES_DIR, "*.json"))
                   if not os.path.basename(p).startswith((".", "_")))
    if os.path.exists(LEGACY_STORY):
        paths = [LEGACY_STORY] + paths
    out = []
    for p in paths:
        try:
            d = json.load(open(p))
            out.append({
                "path": p,
                "title": d.get("title", os.path.basename(p)),
                "theme": d.get("theme", ""),
                "difficulty": (d.get("difficulty") or "").lower(),
                "goal": d.get("goal", ""),
                "n": len(d.get("locations", {})),
            })
        except Exception as e:
            out.append({"path": p, "title": os.path.basename(p), "error": str(e),
                        "theme": "", "difficulty": "", "goal": "", "n": 0})
    return out


def load_story_file(path):
    with open(path, "r") as f:
        return json.load(f)


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    return s[:40] or "story"


def unique_story_path(title):
    os.makedirs(STORIES_DIR, exist_ok=True)
    base = slugify(title)
    path = os.path.join(STORIES_DIR, base + ".json")
    i = 2
    while os.path.exists(path):
        path = os.path.join(STORIES_DIR, f"{base}_{i}.json")
        i += 1
    return path


def save_story_file(story, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(story, f, indent=2, ensure_ascii=False)


@lru_cache(maxsize=1)
def _load_validator():
    import importlib.util
    spec = importlib.util.spec_from_file_location("cyoa_validator", VALIDATOR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def validate_story_dict(story):
    """Return a list of human-readable problems. Empty list == valid & complete."""
    if not isinstance(story, dict):
        return ["story is not a JSON object"]
    problems = [f"missing required field '{f}'"
                for f in ("title", "character_template", "start_location_id", "locations")
                if f not in story]
    if problems:
        return problems
    locs = story.get("locations") or {}
    if story["start_location_id"] not in locs:
        return [f"start_location_id '{story['start_location_id']}' is not a location"]
    try:
        _reach, issues = _load_validator().simulate(story)
        problems += [it["message"] for it in issues]
    except Exception as e:
        problems.append(f"validator crashed on this story: {e}")
    return problems


def balance_check(path, difficulty):
    """Run playtest.py as a quick balance gate. Returns (verdict, [metric lines])."""
    try:
        r = subprocess.run(["python3", "playtest.py", path, difficulty],
                           capture_output=True, text=True, timeout=180)
        out = r.stdout
        verdict = "PASS" if ">>> PASS" in out else ("ADJUST" if "ADJUST" in out else "—")
        lines = [ln.strip() for ln in out.splitlines()
                 if ln.strip().startswith(("cautious win", "heroic death"))]
        return verdict, lines
    except Exception as e:
        return "—", [f"(balance check unavailable: {e})"]


def _extract_json(text):
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    a, b = t.find("{"), t.rfind("}")
    if a == -1 or b == -1 or b < a:
        return None, "no JSON object found in the model output"
    try:
        return json.loads(t[a:b + 1]), None
    except Exception as e:
        return None, f"JSON parse error: {e}"


def _call_model(provider, model, system, messages, api_key):
    """One completion from the chosen provider. messages: [{'role':'user'|'assistant','content'}].
    Returns the model's text. Raises ImportError if the provider SDK isn't installed.
    Retries up to 4 times with exponential backoff on 503 / rate-limit errors."""
    _RETRYABLE = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "rate_limit", "overloaded")
    max_retries, delay = 4, 3

    for attempt in range(max_retries + 1):
        try:
            if provider == "anthropic":
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
                msg = client.messages.create(
                    model=model, max_tokens=GEN_MAX_TOKENS, system=system,
                    messages=[{"role": m["role"], "content": m["content"]} for m in messages],
                )
                return "".join(getattr(b, "text", "") for b in msg.content
                               if getattr(b, "type", "") == "text")
            # default: Google Gemini
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key)
            contents = [types.Content(role=("model" if m["role"] == "assistant" else "user"),
                                      parts=[types.Part(text=m["content"])]) for m in messages]
            resp = client.models.generate_content(
                model=model, contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=GEN_MAX_TOKENS,
                    temperature=0.9,
                    response_mime_type="application/json",
                ),
            )
            return resp.text or ""

        except Exception as e:
            err = str(e)
            if attempt < max_retries and any(k in err for k in _RETRYABLE):
                time.sleep(delay)
                delay *= 2
                continue
            raise


def generate_story_api(theme, difficulty, length, title_hint, api_key, provider, model):
    """Author a story via the chosen provider; validate + repair up to 3 times.
    Returns (story_or_None, problems_list) — problems empty == ready to save."""
    spec = open(GENERATOR_SPEC).read() if os.path.exists(GENERATOR_SPEC) else ""
    system = (
        "You are the story generator for the Quest Book CYOA engine. Return exactly ONE "
        "story as a single JSON object that conforms to the specification below. Output "
        "ONLY the JSON object — no prose, no markdown, no code fences.\n\n"
        "=== SPECIFICATION ===\n" + spec
    )
    user = (
        f"Theme: {theme}\n"
        f"Difficulty: {difficulty}\n"
        f"Target size: about {length} locations, with 3-5 endings (include at least one "
        f"non-victory ending using is_victory:false).\n"
        + (f'Preferred title: "{title_hint}"\n' if title_hint else "")
        + f'Set the top-level "difficulty" field to "{difficulty}" and tune health, check DCs, '
          f"fail_damage and monsters to the {difficulty} preset in the spec. Every location must "
          f"be reachable and able to reach an ending; no dead items; no zero-cost infinite-retry "
          f"checks; give every monster a flee or alternate route."
    )
    messages = [{"role": "user", "content": user}]
    story, problems = None, ["no output produced"]
    for _ in range(3):
        text = _call_model(provider, model, system, messages, api_key)
        story, perr = _extract_json(text)
        if story is None:
            messages += [{"role": "assistant", "content": text or ""},
                         {"role": "user", "content": f"{perr}. Resend ONLY the corrected, complete JSON object."}]
            problems = [perr]
            continue
        problems = validate_story_dict(story)
        if not problems:
            return story, []
        messages += [{"role": "assistant", "content": json.dumps(story)},
                     {"role": "user", "content": "The story failed validation. Fix ALL of these and "
                      "resend ONLY the full corrected JSON:\n- " + "\n- ".join(problems[:25])}]
    return story, problems


# ── dice & text helpers ───────────────────────────────────────────────────────


def roll_dice(dice_type="2d6"):
    num, sides = map(int, dice_type.split("d"))
    return sum(random.randint(1, sides) for _ in range(num))


@lru_cache(maxsize=None)
def _dice_sums(dice_type="2d6"):
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


def animate_roll(placeholder, dice_type="2d6"):
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
    dice       = cond.get("dice_type", "2d6")
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
    dice     = monster.get("dice_type", "2d6")
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
        "Roll <strong>3d6</strong> for each attribute — this is who you are. "
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
                st.session_state.char_rolls[attr] = animate_roll(placeholders[attr], "3d6")
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


def show_library():
    st.markdown("<h1>📖 Quest Book</h1>", unsafe_allow_html=True)
    st.caption("Choose your adventure — or forge a new one.")

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
                f"{_difficulty_badge(s['difficulty'])}</div>"
                f"<div style='color:#6a5a42;font-size:0.74rem;font-family:monospace;margin:0.25rem 0 0.5rem'>"
                f"🌍 {s['theme']} · {s['n']} locations</div>"
                f"<div style='color:#a99878;font-size:0.84rem;line-height:1.5'>{goal}</div></div>",
                unsafe_allow_html=True,
            )
            if st.button("▶  Play", key=f"play_{s['path']}", use_container_width=True):
                select_story(s["path"])
                st.rerun()


def _push_story_to_git(path):
    """Best-effort: commit and push a newly saved story to the git remote."""
    import subprocess
    try:
        subprocess.run(["git", "add", "-f", path], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"Add story: {os.path.basename(path)}"],
            check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], check=True, capture_output=True)
    except Exception:
        pass  # non-fatal — story is already saved to disk


def _do_generate(theme, difficulty, length, title_hint, api_key, provider, model):
    try:
        story, problems = generate_story_api(theme, difficulty, length, title_hint,
                                             api_key, provider, model)
    except ImportError:
        pkg = PROVIDER_PKG.get(provider, provider)
        return {"ok": False, "errors": [f"The '{pkg}' Python package isn't installed. "
                                        f"Install it with:  pip install {pkg}"]}
    except Exception as e:
        return {"ok": False, "errors": [f"API call failed: {e}"]}
    if story and not problems:
        path = unique_story_path(story.get("title") or theme)
        save_story_file(story, path)
        _push_story_to_git(path)
        verdict, vlines = balance_check(path, difficulty)
        return {"ok": True, "path": path, "title": story.get("title") or theme,
                "verdict": verdict, "vlines": vlines}
    return {"ok": False, "errors": problems or ["The model could not produce a valid story."]}


def show_create_page():
    if st.button("←  Back to library"):
        st.session_state.screen = "library"
        st.session_state.pop("gen_result", None)
        st.rerun()
    st.markdown("<h1>✨ Forge a New Story</h1>", unsafe_allow_html=True)

    res = st.session_state.get("gen_result")
    if res is not None:
        if res.get("ok"):
            st.success(f"Created **“{res['title']}”** — saved to `{res['path']}`.")
            badge = {"PASS": "✅ balanced for its difficulty",
                     "ADJUST": "⚠ slightly off target difficulty (still valid & playable)"}.get(res.get("verdict"), "")
            if badge:
                st.caption(f"Balance: {badge}")
            for ln in res.get("vlines", []):
                st.caption(f"· {ln}")
            c1, c2 = st.columns(2)
            if c1.button("▶  Play it now", use_container_width=True):
                select_story(res["path"])
                st.rerun()
            if c2.button("✨  Create another", use_container_width=True):
                st.session_state.pop("gen_result", None)
                st.rerun()
        else:
            st.error("Couldn't generate a valid story. Try again, or tweak the theme.")
            for e in res.get("errors", [])[:12]:
                st.caption(f"· {e}")
            if st.button("↩  Try again", use_container_width=True):
                st.session_state.pop("gen_result", None)
                st.rerun()
        return

    st.markdown(
        "<div style='background:#141008;border-left:3px solid #8b6914;border-radius:0 6px 6px 0;"
        "padding:1rem 1.3rem;margin:0.4rem 0 1rem;color:#c8b49a;font-size:0.9rem;line-height:1.6'>"
        "Describe a setting and pick a difficulty. Claude writes a full branching adventure, then "
        "the app validates and balance-checks it before adding it to your library."
        "</div>", unsafe_allow_html=True)

    theme = st.text_input("Theme / setting",
                          placeholder="e.g. Pirate ghost ship · Cyberpunk heist · Norse myth · Haunted Mars colony")
    c1, c2 = st.columns([2, 3])
    difficulty = c1.radio("Difficulty", DIFFICULTIES, index=1)
    length = c2.slider("Approx. number of locations", 8, 20, 14)
    title_hint = st.text_input("Title (optional)", placeholder="Leave blank to let the model name it")

    detected = gen_provider()
    with st.expander("⚙  Model & API key", expanded=not env_api_key(detected)):
        provs = ["google", "anthropic"]
        provider = st.selectbox("Provider", provs, index=provs.index(detected),
                                format_func=lambda p: PROVIDER_LABEL[p])
        model = st.text_input("Model", value=gen_default_model(provider), key=f"model_{provider}")
        env_key = env_api_key(provider)
        if env_key:
            api_key = env_key
            st.caption(f"Using your {PROVIDER_LABEL[provider]} key from the environment.")
        else:
            key_env = "GOOGLE_API_KEY" if provider == "google" else "ANTHROPIC_API_KEY"
            api_key = st.text_input(f"{PROVIDER_LABEL[provider]} API key", type="password",
                                    key=f"key_{provider}",
                                    help="Used only for this request; not written to disk.")
            st.caption(f"Tip: set `{key_env}` in your environment to skip this field.")

    if st.button("✨  Generate Story", use_container_width=True, disabled=not theme.strip()):
        if not api_key:
            st.warning(f"A {PROVIDER_LABEL[provider]} API key is required "
                       "(set it in the environment or paste it under **Model & API key**).")
        else:
            with st.spinner("Summoning a new world… the model is writing it and the validator is "
                            "checking every path. This can take up to a minute."):
                st.session_state.gen_result = _do_generate(
                    theme.strip(), difficulty, length, title_hint.strip(), api_key, provider, model)
            st.rerun()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
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
            f"This is a story-data bug — run the validator on story.json."
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
            dice  = cond.get("dice_type", "2d6")
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
            dice    = monster.get("dice_type", "2d6")
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
        m_dice  = monster.get("dice_type", "2d6")
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
                            f"{odds_label(cc.get('dice_type','2d6'), cc['check_value'], fa, b)}]")
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
            odds = odds_label(cond.get("dice_type", "2d6"), cond["check_value"], attr_val, bonus)
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
