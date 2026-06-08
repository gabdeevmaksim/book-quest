# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Quest Book is a Choose Your Own Adventure (CYOA) RPG web app built with Streamlit. The
main screen is a **library** of stories (`stories/*.json`); the player picks one to play,
or generates a brand-new one from a theme on the in-app **Create a New Story** page (AI
generation via the Anthropic API). The engine renders an interactive, branching narrative
with RPG mechanics: attribute checks, dice rolls, monster combat, items, and healing.

## Running the App

**Local (activate venv first):**
```bash
source venv/bin/activate  # or create: python3 -m venv venv && pip install -r requirements.txt
streamlit run app.py
```

**Docker:**
```bash
docker-compose up --build
```

App runs at `http://localhost:8501`. In-app story creation needs a model API key — a Google
Gemini key (`GOOGLE_API_KEY`, the default provider) or an Anthropic key (`ANTHROPIC_API_KEY`) —
set in the environment or pasted into the Create page.

## Story Pipeline

1. **Create** a story one of two ways:
   - **In-app**: *Create a New Story* → enter a theme + difficulty → Claude writes it, and
     the app auto-validates, balance-checks, and saves it to `stories/`.
   - **From the skill / Claude Code**: the `cyoa-generator` skill writes `stories/<slug>.json`.
2. **Validate** link integrity & reachability:
   ```bash
   python3 cyoa-skills/cyoa-validator/scripts/validate_story.py stories/<slug>.json
   ```
3. **Balance-check** against the target difficulty (PASS / ADJUST verdict):
   ```bash
   python3 playtest.py stories/<slug>.json [easy|normal|hard]
   ```
4. **Play** – launch the app; the gallery auto-discovers every `stories/*.json`.

## Architecture

**`app.py`** — Streamlit app with four screens routed via `st.session_state.screen` /
`active_story`: **library gallery** (`show_library` over `list_stories`), **create page**
(`show_create_page` → `generate_story_api` → `validate_story_dict` → `balance_check` →
`save_story_file`), **character creation**, and the **game**. Per-run game state in
`st.session_state`: `active_story`, `current_loc`, `hp`/`max_hp`, `attributes`, `inventory`,
`locations` (deepcopy; monsters deleted after defeat), `log`, `game_over`, `pending_choice`/
`pending_combat`. The game no longer hard-crashes on a broken `target_id` — it shows an error
and a way back to the library — but you should still validate every story.

**`stories/`** — the story library. Each `*.json` is one adventure; the gallery shows its
`title`, `theme`, `difficulty`, and `goal`. New stories are saved here.

**`story.json`** (repo root) — legacy single-story file; used only as a fallback when
`stories/` is empty.

**Story schema** (all engine-honored fields):
```
title, theme, difficulty, goal,
character_template { health, strength, agility, stamina },
items { id: { name, icon, description, use?:{heal:N} } },
start_location_id,
locations { id: {
  description, is_end, is_victory?, loot?:[item],
  monster?: { name, strength(=DC), fail_damage, dice_type?, attribute? },
  choices: [ {
    text, target_id, is_flee?, requires_item?, gives_item?, heals?, consumes_item?,
    condition?: { attribute, check_value, dice_type, fail_damage, fail_target?,
                  item_bonus?:{item,bonus} }
  } ]
} }
```

**`cyoa-skills/`** — Claude skills (`.skill` files are zip archives of these dirs):
- `cyoa-generator`: the authoritative story-generation spec (schema, design rules, difficulty
  presets). Also used verbatim as the system prompt by the in-app generator.
- `cyoa-validator`: `validate_story.py` — link/reachability/reach-an-ending checks
  (cycle-safe reverse-reachability) with an optional `--fix`.

**`playtest.py`** — Monte-Carlo balance harness. `python3 playtest.py <story> [difficulty]`
runs 20k playthroughs across random/cautious/heroic policies and prints a difficulty verdict.

## Key Constraints

- A story is loaded into `st.session_state.active_story` when selected; `locations` is a
  deepcopy, so combat mutations don't touch the file on disk.
- Monsters are removed from `st.session_state.locations` after defeat. During an encounter
  only the Fight button and `is_flee` choices show; non-flee choices appear post-defeat.
- Attribute checks: `dice_roll + attribute (+ item_bonus) >= check_value`; failure costs
  `condition.fail_damage` (default 2). Combat: `dice_roll + attribute >= monster.strength`.
- Optional choice fields (`condition`, `requires_item`, `gives_item`, `heals`, etc.) all have
  safe defaults, so older stories without them still run.

## Config and Environment

Paths: `QUEST_STORIES_DIR` (`stories`), `QUEST_STORY` (`story.json`, legacy fallback).

In-app generation is **provider-agnostic** — it auto-selects from whichever key is set, or
honors `QUEST_GEN_PROVIDER` (`google` | `anthropic`):
- **Google Gemini** (default): `GOOGLE_API_KEY` (or `GEMINI_API_KEY`); default model `gemini-3.5-flash`.
- **Anthropic Claude**: `ANTHROPIC_API_KEY`; default model `claude-sonnet-4-6`.

`QUEST_GEN_MODEL` overrides the model for the active provider. There is still no `config.yaml`;
if you add more hardcoded paths, consider introducing one.
