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

**Production (CI/CD):** pushing to `master` runs `.github/workflows/deploy.yml` — tests
(`python -m pytest tests`), then an SSH deploy to the DigitalOcean droplet via
`scripts/deploy.sh` (pull → optional `.env` from the `DOTENV` secret → `docker compose up -d
--build` → health check). Pushes touching only `stories/`, `docs/`, `*.md` don't redeploy.
Setup and secrets: `DEPLOY.md`. Run the tests locally before pushing.

App runs at `http://localhost:8501`. In-app story creation needs a model API key — a Google
Gemini key (`GOOGLE_API_KEY`, the default provider) or an Anthropic key (`ANTHROPIC_API_KEY`) —
set in the environment (users are never asked for their own key).

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
5. **Story review** (continuity; one cheap model call — needs a model key):
   ```bash
   python3 narrative_review.py stories/<slug>.json
   ```
6. **Play** – launch the app; the gallery auto-discovers every `stories/*.json`.

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

**Story schema** (all engine-honored fields):
```
title, theme, difficulty, goal, prologue,
language?, language_level?,   # any language + CEFR A1-C2 (defaults: English / C2)
character_template { health, strength, agility, stamina },
items { id: { name, icon, description, use?:{heal:N} } },
start_location_id,
locations { id: {
  description, is_end, is_victory?, loot?:[item],
  monster?: { name, strength(=DC), fail_damage, dice_type?, attribute?,
              success_text, fail_text },
  choices: [ {
    text, target_id, is_flee?, requires_item?, gives_item?, heals?, consumes_item?,
    trap_hint?,              # entrance to a hinted dead-end branch (phrase from the description)
    condition?: { attribute, check_value, dice_type, fail_damage,
                  success_text, fail_text, item_bonus?:{item,bonus},
                  fail_target? }   # LEGACY only — honoured for old stories, flagged for new ones
  } ]
} }
```

**`game_rules.py`** — the single source of truth for challenge mechanics, imported by both
`app.py` and `playtest.py` (so the simulator can't drift from the game): one-roll checks and
monsters, fail-forward damage, outcome texts (with defaults for old stories), item bonuses,
odds, legacy `fail_target`, and `trap_band(difficulty, n_locations)` (dead ends per story).

**`narrative_review.py`** — the story-review agent (4th gate). One cheap-model call reads a
compact outline of the whole story (scenes, "reached from" paths, outcome texts, trap markers)
and returns JSON issues — transition, outcome, introduced-before-used, contradiction, ending —
each `major`/`minor`. Any major fails the gate. `story_engine.create_story` runs it only after
validate/coherence/balance pass and feeds majors into the repair loop; its cost goes into the
usage/budget ledger; an API failure or unreadable reply → `skipped` (never blocks). Config:
`QUEST_REVIEW=0` (off), `QUEST_REVIEW_PROVIDER`, `QUEST_REVIEW_MODELS` (default Haiku 4.5 /
Gemini 2.5 Flash). CLI: `python3 narrative_review.py stories/<slug>.json`;
`story_agent.py --audit X.json --review`.

**`scripts/regenerate_library.py`** — rebuilds library stories under the current rules with
the same title/theme/difficulty/language/filename via `create_story`; archives the old version
to `stories/_archive/` (gitignored) and keeps it if the new one fails a gate. Run on the droplet:
`docker compose exec quest-book python3 scripts/regenerate_library.py [--dry-run] [--push]`.

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

**`feedback.py`** — Streamlit-free player feedback: `submit()` appends to `state/feedback.jsonl`
and notifies the owner on Telegram (`QUEST_TG_BOT_TOKEN` + `QUEST_TG_CHAT_ID`; hourly cap
`QUEST_FEEDBACK_NOTIFY_PER_HOUR`); never raises. `python3 feedback.py` lists entries. In
`app.py`: a "Send feedback" popover (library footer + game sidebar) and an end-screen star
rating; game context is attached; per-session cooldown/cap kept in `fbmeta_*` session keys,
which `clear_session()` preserves across navigation.

**`.streamlit/config.toml`** — dark theme in the app's colours (amber primary), so native
widgets match the hand-styled CSS in `app.py`.

**`playtest.py`** — Monte-Carlo balance harness. `python3 playtest.py <story> [difficulty]`
runs 20k playthroughs across random/cautious/heroic policies and prints a difficulty verdict.
Resolves challenges through `game_rules.py`; the cautious player heeds trap hints, the heroic
one ignores them. Importable: `simulate(story, n)` / `analyze(story, difficulty)`.

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
- **Every challenge is passable (fail-forward).** Attribute checks:
  `dice_roll + attribute (+ item_bonus) >= check_value`. Success → through cleanly; failure →
  the hero STILL continues to `target_id` (and gets the choice's items) but loses
  `condition.fail_damage` (default 2). A run only ends early at HP 0 (or in a bad ending).
  The matching `success_text`/`fail_text` is shown in an outcome card after the roll
  (`st.session_state.last_outcome`).
- **Monsters are one roll** (`dice_roll + attribute >= monster.strength`): won or lost, the
  encounter is over and the monster is removed from `st.session_state.locations`; then the
  location's non-flee choices appear. During the encounter only Fight and `is_flee`
  (alternative approach) choices show. Every monster location needs a non-flee choice.
- **Dead ends**: choices with `trap_hint` lead into hinted, played-out dead-end branches —
  easy 0, normal 1 (1–2 above 14 locations), hard 2–4 (`game_rules.trap_band`); enforced by
  the coherence gate along with outcome texts. **Easy** mode has a "↩ Go back" button
  (`st.session_state.history`); going back never re-grants items or revives monsters.
- Balance targets are the same bands as before, but presets were recalibrated for
  fail-forward (stakes = challenges on every route to victory) — see the generator spec.
- **Dice system**: attributes are rolled **2d6** at character creation (range 2–12, avg 7);
  checks and combat roll **1d6** by default (engine default when `dice_type` is omitted).
  DC 13–14 is unreachable without an item bonus — items are deliberately the lever that
  turns impossible checks into fair ones. Difficulty presets live in the cyoa-generator spec.
  `QUEST_PLAYTEST_N` overrides the Monte-Carlo run count (default 20000) for fast tuning.
- Optional choice fields (`condition`, `requires_item`, `gives_item`, `heals`, etc.) all have
  safe defaults, so older stories without them still run.

## Config and Environment

Paths: `QUEST_STORIES_DIR` (default `stories`).

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
- **Google Gemini** (default, **free tier only** for now): `GOOGLE_API_KEY` (or `GEMINI_API_KEY`).
  Free-tier limits are tiny and **per model**: each Flash model 5 req/min · 20 req/day; Flash Lite
  3.5/3.1 15/min · 500/day; per project; reset at midnight Pacific. So the generation chain rotates
  through every Flash model `gemini-3.8-flash → 3.7 → 3.6 → 3.5 → 3 → 2.5-flash` (≈120 writer
  calls/day) and the story review uses Flash Lite `gemini-3.5-flash-lite → 3.1-flash-lite →
  2.5-flash-lite`, so reviews never eat writing quota. `QUEST_GOOGLE_TIER=free` (default) makes
  Gemini calls cost $0 in the budget ledger; set `paid` if billing is enabled. Pro models are
  paid-only — don't put them in the chains.
- **`quota.py`** — the free-tier guard. `call_model` asks `quota.reserve(model)` before every
  request to a tracked model: counted → go; per-minute window full → wait (≤ `QUEST_QUOTA_MAX_WAIT`,
  65 s) or skip; day used up → `QuotaSkip`, the fallback chain moves on without a call. 429/404
  answers are learned (`note_error`) and are NOT blindly retried. `generation_slot()` allows one
  story generation at a time (app + CLI scripts; others queue). `capacity()` = writer calls left
  ÷ measured average calls per story → the Create page's "≈ N stories left today" counter; a
  per-player daily cap (`QUEST_STORIES_PER_PLAYER`, default 3, keyed by a hashed IP or the
  session). State in `state/quota.json` (file-locked; gitignored). Limits table in `quota.py`
  (copied from AI Studio → Rate limit), override with `QUEST_MODEL_LIMITS` JSON. CLI:
  `python3 quota.py` (today's usage + capacity), `python3 quota.py --check-models`.
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
