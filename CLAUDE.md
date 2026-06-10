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

Two orchestrators run the whole pipeline (draft → validate → coherence → balance, with a repair
loop): the **`story-smith` agent** (`.claude/agents/story-smith.md`, for Claude Code), and the
standalone **`story_agent.py`** CLI, which needs only a free Google Gemini key — no Claude Code,
no Anthropic (`GOOGLE_API_KEY=… python3 story_agent.py "<theme>" -d hard`). Stories can be
generated in **any language at a CEFR level** (`-l/--lang Italian --level B1` on the CLI;
Language + level controls on the in-app Create page) — useful for language learners. Manually,
the steps are:

1. **Create** a story:
   - **In-app**: *Create a New Story* → theme + difficulty → the app writes it (Gemini/Claude),
     auto-validates + balance-checks, and saves to `stories/`.
   - **Skill / agent**: the `cyoa-generator` skill or `story-smith` agent writes `stories/<slug>.json`.
2. **Validate** links & reachability:
   ```bash
   python3 cyoa-skills/cyoa-validator/scripts/validate_story.py stories/<slug>.json
   ```
3. **Coherence & pre-history** (flags chaotic maps, free-movement loops, thin openings):
   ```bash
   python3 cyoa-skills/cyoa-validator/scripts/coherence_report.py stories/<slug>.json
   ```
4. **Balance-check** vs the target difficulty (PASS / ADJUST verdict):
   ```bash
   python3 playtest.py stories/<slug>.json [easy|normal|hard]
   ```
5. **Play** – launch the app; the gallery auto-discovers every `stories/*.json`.

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
title, theme, difficulty, goal, prologue,
language?, language_level?,   # any language + CEFR A1-C2 (defaults: English / C2)
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
  (cycle-safe reverse-reachability) with an optional `--fix`; and `coherence_report.py` —
  connectivity + pre-history + quality linter: free-movement loops, backtrack ratio,
  prologue/opening, **linearity** (fails corridors: >40% single-choice locations, avg
  choices <1.6, or 4+ single-choice locations in a row), **item grounding** (every
  `loot`/`gives_item` grant must be mentioned in the location description or choice text —
  language-agnostic token match on the item's name+description), and **double-collectable
  items** (same item grantable twice on one reachable path). Prints `COHERENCE: OK`/`REVIEW`.

**`.claude/agents/story-smith.md`** — orchestrator subagent that runs the whole pipeline
(draft → validate → coherence → balance) with a repair loop; also audits/repairs existing stories.

**`playtest.py`** — Monte-Carlo balance harness. `python3 playtest.py <story> [difficulty]`
runs 20k playthroughs across random/cautious/heroic policies and prints a difficulty verdict.

**`story_engine.py`** — Streamlit-free core shared by `app.py` and `story_agent.py`: provider
config, the model call with retry/backoff + **`call_with_fallback`** (advances down a model chain
when one hits its free-tier limit), prompt builders, the three gates
(`validate_story_dict`/`coherence_check`/`balance_check`), and **`create_story`** — the enforced
pipeline that loops draft → validate → coherence → balance with repair and saves only when every
gate is green. Both the in-app Create page (`_do_generate`) and `story_agent.py` call
`create_story`, so passing all gates is a necessary step for any story to enter the library.
`app.py` imports from it, so the engine module must ship alongside the app (it's in the Dockerfile).

**`story_agent.py`** — standalone CLI orchestrator. Drafts via the chosen provider and loops
draft → validate → coherence → balance until all gates pass, then saves to `stories/`. Needs only
`google-genai` + a free `GOOGLE_API_KEY`; runs on any server. `--audit <story.json>` gate-checks
an existing story without generating.

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

**S3-compatible story storage** (optional; AWS S3 / Cloudflare R2 / Backblaze B2 / MinIO):
set `QUEST_S3_BUCKET` to enable. The bucket is the durable cross-machine store; `stories/`
acts as a local cache — new stories are uploaded on save (status shown in the UI/CLI), and the
app pulls missing/newer stories at startup (`sync_stories_from_s3`). Config: `QUEST_S3_ENDPOINT`
(for R2/B2/MinIO), `QUEST_S3_REGION`, `QUEST_S3_PREFIX` (default `stories/`); credentials via
standard `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`. One-time migration / manual sync:
`python3 story_agent.py --s3-sync` (pulls newer, uploads local-only). Needs `boto3`.

**Git auto-push of new stories** (`story_engine.push_story_to_git`, used by the Create page and
`story_agent.py --push`): commits `Add story: <file>` and pushes. It returns `(ok, detail)` and
the UI/CLI display the result — failures are never silent. Headless/Docker: HTTPS push auth via
`QUEST_GIT_TOKEN` (or `GITHUB_TOKEN`, a GitHub PAT); identity fallback `QUEST_GIT_NAME` /
`QUEST_GIT_EMAIL` (defaults `Quest Book <quest-book@localhost>`); `safe.directory` is handled.

In-app generation is **provider-agnostic** — it auto-selects from whichever key is set, or
honors `QUEST_GEN_PROVIDER` (`google` | `anthropic`):
- **Google Gemini** (default): `GOOGLE_API_KEY` (or `GEMINI_API_KEY`); chain `gemini-3.5-flash → gemini-2.5-flash → gemini-2.5-flash-lite`.
- **Anthropic Claude**: `ANTHROPIC_API_KEY`; chain `claude-sonnet-4-6 → claude-haiku-4-5-20251001`.

**Model fallback:** generation tries the models in order and auto-advances to the next when one
hits its free-tier limit (or is unavailable). `QUEST_GEN_MODELS="m1,m2,..."` sets the chain;
`QUEST_GEN_MODEL="m"` pins a single model. There is still no `config.yaml`; if you add more
hardcoded paths, consider introducing one.

## License

`LICENSE` is the **PolyForm Noncommercial License 1.0.0** — the software may be used only for
noncommercial purposes (personal/hobby use, and charities, schools, research, and other
nonprofit organizations all qualify). Commercial use is not granted. This is source-available,
not OSI open-source. Third-party dependencies (Streamlit, google-genai, anthropic) keep their
own licenses.
