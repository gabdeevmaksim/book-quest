# Quest Book — Roadmap

Living plan for the game. Decisions recorded here are the owner's calls; update this file as
phases land.

## Done

- **Library cleanup** — duplicate stories removed.
- **Owner-funded generation** — no "bring your own API key"; the owner's key is always used.
- **Cost tracking + monthly budget cap** — per-generation token/cost logging, a monthly ledger
  (`state/usage.json`), auto-fallback to the free Google chain once `QUEST_MONTHLY_BUDGET_USD`
  is reached, with a "budget used up — you can still play the library" message.
- **`compare_models.py`** — benchmark for $/successful story across models.
- **Landing page + donations** — `docs/index.html` (GitHub Pages), `.github/FUNDING.yml`
  (Ko-fi + GitHub Sponsors live), support links on the landing page, library and game sidebar.
- **Phase 1 — Share + deep links** ✅
- **Phase 2 — Feedback window** ✅
- **Phase 3 — Fail-forward mechanics, hinted dead ends, Go Back** ✅ (library regeneration pending)
- **Phase 4 — Story-review agent** ✅ (4th gate: continuity review by a cheap model)
- **Git auto-push of stories removed** — stories live on the server + S3; player content stays
  out of the public repo; no GitHub write token on the server.
- **Free-tier quota guard** ✅ — `quota.py`: per-model RPM/TPM/RPD tracking with the AI Studio
  limits, midnight-Pacific reset, skip/wait instead of hitting 429s, writer rotation across all
  Flash models + reviews on Flash Lite, one generation at a time (queue), per-player daily cap,
  and a "≈ N stories can still be created today" counter on the Create page.
- **CI/CD** ✅ — push to `master` → tests → automatic deploy to the droplet (see `DEPLOY.md`).
  Secrets can live in GitHub (`DOTENV`). Docker image moved to Python 3.12.

## Phase 1 — Share + deep links ✅

- `?story=<slug>` opens a story directly; the address bar updates when a story is picked, so
  any game URL is shareable. Unknown/crafted slugs fall back to the library with a notice.
- Share menu (Telegram · WhatsApp · X · copy link) on every library card and on the end
  screen ("I conquered … with 7/18 HP left!" / "I met my end in …"). Styled to match the dark
  UI (text "Share" button, dark dropdown).
- `QUEST_PUBLIC_URL` sets the base URL in share links (defaults to the droplet IP — set it to
  the real domain once bought).

## Phase 2 — Feedback window ✅

- **"Send feedback"** popover in the library footer and the game sidebar: kind
  (bug / story / idea / other), optional 1–5 stars, message, optional contact.
- **End screen**: "How did you like this story?" star rating + optional comment, once per
  story per session.
- Context attached automatically: story, difficulty, language, location, HP, outcome, screen,
  app version (git hash) — nothing else beyond what the player types.
- **Delivery (decision A + B):** every submission is appended to `state/feedback.jsonl` on the
  droplet (never lost) and sent to the owner's Telegram (`QUEST_TG_BOT_TOKEN`,
  `QUEST_TG_CHAT_ID`). Read the file with `python3 feedback.py`.
- **Anti-spam:** message/contact length caps, 60 s cooldown and max 5 per session (survives
  going back to the library), Telegram capped at 30 messages/hour (rest still saved).
  The planned honeypot was dropped — Streamlit forms aren't plain HTML forms, so form-filling
  bots can't reach them.
- **Dark theme** (`.streamlit/config.toml`) so the form's inputs, radios and buttons match the
  UI — this also fixes the white inputs on the Create page.
- Later (backlog): average story ratings on library cards / sort by rating.

## Phase 3 — Mechanics: every challenge is passable, dead ends with hints, Go Back ✅

**Decisions**
- **Every obstacle is passable.** A failed check never blocks or loops: the hero gets through
  but pays HP, and the story moves on to the same destination.
- **Monsters work the same way.** An encounter is resolved by one roll: win → the monster is
  beaten and you move on; lose → you still get past it, but wounded (−HP), with a different
  outcome text ("you drive the ghoul back, but its claws rake your side"). Alternative
  approaches stay as choices with their own attribute and outcomes (fight with strength,
  slip past with agility, outlast it with stamina).
- **Consequences are realistic and match the approach**, for obstacles and monsters alike,
  e.g. a locked door:
  - *Agility* (slip the latch / squeeze through): fail → "the splintered frame slices your
    forearm" (−HP).
  - *Strength* (shoulder-charge it): success → door bursts open; fail → "the door gives way,
    but your shoulder takes the blow" (−HP).
  - *Stamina* (hammer at the hinges for minutes): fail → exhaustion, scraped knuckles (−HP).
  Damage scales with how dangerous the approach is and with the difficulty preset.
- Since nothing blocks, **HP is the only stake**: a run dies only from accumulated damage, so
  health and damage per difficulty must be retuned so careless/unlucky play can still die.
- **Dead-end (trap) branches, always hinted.** Wrong decisions can lead into an inescapable
  situation that is *played out* over 2–3 narrated locations before a non-victory ending.
  Every trap is foreshadowed so a careful reader can avoid it.
  - **easy**: none — and a **"↩ Go back"** button (engine-level history; going back never
    re-grants items or revives monsters).
  - **normal**: 1–2 traps depending on length (1 up to ~14 locations, 2 for longer stories).
  - **hard**: 2–4 traps scaling with length.

**Built** ✅
1. **`game_rules.py`** — one shared rules module for the game and the simulator: one-roll
   checks and monsters, fail-forward damage, outcome texts, item bonuses, `trap_band()`.
2. **Schema**: `success_text` / `fail_text` on every check and monster; `trap_hint` (a phrase
   from the description) marks a dead-end entrance; `fail_target` retired (still honoured for
   old stories so they keep working until regenerated).
3. **Engine**: outcome card after every roll (also on the game-over screen); one-roll monster
   encounters, then the onward choices; failure still grants the choice's items; easy-mode
   "↩ Go back".
4. **`playtest.py`** rebuilt on the shared rules (no retries; careful player heeds hints, heroic
   ignores them); target bands unchanged.
5. **Coherence gate**: outcome texts present, no `fail_target`, monster locations have a way
   onward, dead-end count per difficulty/length, each a real 2+ location dead end, hint phrase
   present in the scene, no untagged dead ends or instant-doom choices; easy has none.
6. **Presets recalibrated** by simulation (stakes = challenges on every route to victory):
   easy HP 22–28, DC 7–9, damage 3–5; normal HP 18–22, DC 8–11, damage 4–6; hard HP 16–20,
   DC 9–12, damage 5–7; monsters a notch higher. Spec, reference sample, generator prompt
   (states the exact dead-end count) and `.skill` archives updated.
7. **Library**: decision — **regenerate all 7 stories** (same title/theme/difficulty/language/
   filename) with `scripts/regenerate_library.py` instead of converting them by hand.

## Phase 4 — Story-review agent ✅

- **`narrative_review.py`**: one cheap-model call (Haiku 4.5 / free Gemini 2.5 Flash) reads a
  compact outline of the whole story — every scene with the places it can be reached from,
  every choice → destination, outcome texts, dead-end markers — and reports continuity
  problems as JSON: **transition** (scene doesn't follow from the choice), **outcome** (a
  success/fail text that clashes with the next scene or stops the hero), **introduced**
  (something used before the player could have met it on that path), **contradiction**,
  **ending** (victory doesn't pay off the goal). Each is `major` or `minor`.
- **4th gate** in `create_story`, run only after validate/coherence/balance pass (no money
  spent on broken drafts). Major issues fail it and go back into the repair loop; minor ones
  are reported only. API error / unreadable reply → "skipped", never blocks.
- Cost goes into the usage/budget ledger (≈ a cent per review with Haiku). Config:
  `QUEST_REVIEW=0` to turn off, `QUEST_REVIEW_PROVIDER`, `QUEST_REVIEW_MODELS`.
- Standalone: `python3 narrative_review.py stories/<slug>.json`, or
  `python3 story_agent.py --audit stories/<slug>.json --review`.
- Order decided: build this **before** regenerating the library, so every regenerated story is
  reviewed too.

## Backlog

- **Streamlit `use_container_width` → `width="stretch"`**: deprecated and being removed
  release by release; CI (latest Streamlit) will go red the day it breaks — migrate before then.

- **Interface in the story's language** (deferred): UI strings layer — built-in English +
  Russian dictionaries; the generator adds a `ui` block of translated labels to each story for
  any other language; English fallback for old stories. Translate character creation (intro,
  attribute names/descriptions), all buttons, roll labels, outcome/log messages, end screens,
  share texts and the feedback form. Backfill script for existing non-English stories.

- **Vocabulary helper** (deferred): per-location glossary written at generation time, word
  look-up, personal word list with story examples, copy / CSV (Anki) export.

## Owner to-dos

- **Models: free-tier Gemini only (for now).** Stories are written by rotating through the
  Flash models (3.8 first; each has only 20 requests/day) and checked by Flash Lite (500/day).
  Remove any old `QUEST_GEN_MODEL=claude-…` / `QUEST_GEN_PROVIDER=anthropic` from `.env` (see
  `DEPLOY.md`). After deploying run `python3 quota.py --check-models` once.
  Later: compare writers side by side with `compare_models.py --models
  gemini-3.8-flash,gemini-3.5-flash,gemini-2.5-flash --runs 2` (free — uses quota) and keep the
  lowest one whose stories still pass.
- **Regenerate the library** once Phases 3 + 4 are deployed (every story now also passes the
  story review):
  `docker compose exec quest-book python3 scripts/regenerate_library.py --dry-run`, then
  `docker compose exec quest-book sh -c "python3 scripts/regenerate_library.py"`. Re-run
  `--only <file>` for any story that didn't pass every gate.
- Remove `QUEST_GIT_TOKEN` / `GITHUB_TOKEN` from the droplet `.env` / `DOTENV` — git auto-push
  of stories is gone, so the server no longer needs a GitHub write token.
- One-time: make sure S3 has every story — `docker compose exec quest-book sh -c
  "python3 story_agent.py --s3-sync"`.
- Update `.claude/agents/story-smith.md` (local, gitignored — I couldn't edit it): it still
  mentions retry checks / flee routes; it defers to the spec, which is current.

- CI/CD one-time setup (`DEPLOY.md`): compose plugin on the droplet, deploy key, GitHub secrets.

- Add `QUEST_TG_BOT_TOKEN` + `QUEST_TG_CHAT_ID` to `.env` / the `DOTENV` secret (bot is created)
  so feedback reaches Telegram — without them it's still saved on the droplet.
- Buy a domain → point it at GitHub Pages (landing) and a `play.` subdomain at the droplet;
  then set `QUEST_PUBLIC_URL` and repoint the landing page's Play button.
- Enable GitHub Pages: Settings → Pages → branch `master`, folder `/docs`.
