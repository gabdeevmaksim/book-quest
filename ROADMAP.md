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
  (Ko-fi live), Ko-fi links in the app.
- **Phase 1 — Share + deep links** ✅
- **CI/CD** ✅ — push to `master` → tests → automatic deploy to the droplet (see `DEPLOY.md`).
  Secrets can live in GitHub (`DOTENV`). Docker image moved to Python 3.12.

## Phase 1 — Share + deep links ✅

- `?story=<slug>` opens a story directly; the address bar updates when a story is picked, so
  any game URL is shareable. Unknown/crafted slugs fall back to the library with a notice.
- Share menu (Telegram · VK · WhatsApp · X · copy link) on every library card and on the end
  screen ("I conquered … with 7/18 HP left!" / "I met my end in …").
- `QUEST_PUBLIC_URL` sets the base URL in share links (defaults to the droplet IP — set it to
  the real domain once bought).

## Phase 2 — Feedback window

A "💬 Feedback" button so players can report bugs, rate a story and suggest ideas.

**In the app**
- Sidebar button during play + a link in the library footer → a small form: type
  (bug / story / idea / other), 1–5 star rating, message, optional contact (email/Telegram).
- End screen: a one-tap "Rate this story ★★★★★" prompt + optional comment.
- Context is attached automatically so reports are actionable: story, difficulty, language,
  current location, HP, outcome — never anything the player didn't type besides that.
- Anti-spam: length cap, one submission per minute per session, honeypot field.
- Later: average story ratings shown on library cards / used to sort the library.

**Where it goes** — *owner to decide*. Options:

| Destination | Setup | Owner gets notified | Private | Notes |
|---|---|---|---|---|
| **A. Server file** `state/feedback.jsonl` | none | no — read it on the droplet | ✅ | Always works; the baseline for every option below |
| **B. Telegram bot** → your chat | create bot via @BotFather, 2 env vars | ✅ instantly, on your phone | ✅ | Free; same app players already use for sharing |
| **C. Email** to your inbox | SMTP creds (e.g. Gmail app password) | ✅ | ✅ | Familiar; spam-filter and credential hassle |
| **D. GitHub Issues** via API | GitHub token | ✅ (GitHub notifications) | ❌ public | Great for bugs, wrong for personal messages; spam lands in public |
| **E. External form** (Google Forms / Tally) | create the form | ✅ | ✅ | No code, but players leave the game and context isn't attached |

**Decision: A + B** — every submission is saved on the server (nothing is ever lost, even if
Telegram is down) and pushed to the owner's Telegram instantly with the story/location
context. Bugs worth tracking can be turned into GitHub issues by hand.
Config: `QUEST_TG_BOT_TOKEN`, `QUEST_TG_CHAT_ID` (if unset, feedback is still saved to the file).

## Phase 3 — Mechanics: every challenge is passable, dead ends with hints, Go Back

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

**Work**
1. Schema: `success_text` / `fail_text` on every check and every monster; checks and
   encounters always continue (`fail_target` retired for checks); `trap: true` marks a trap
   entrance.
2. Engine (`app.py`): show the outcome text + HP loss after every roll; one-roll monster
   encounters (then the location's onward choices appear); easy-mode Go Back stack.
3. `playtest.py`: model fail-forward obstacles + monsters (no retries) and trap branches
   (careful player follows hints); recalibrate easy/normal/hard bands.
4. Validator: every check/monster has outcome texts; easy → every location can still reach a
   victory; normal/hard → trap count within the band, each ending in a narrated non-victory
   ending (2+ steps). Coherence: flag traps with no hint in the preceding text.
5. Generator spec (`cyoa-generator/SKILL.md`): approach-specific realistic injuries for
   obstacles and monsters, damage scaling, hinted traps per difficulty.
6. Migrate the existing library: a script converts checks + monsters to fail-forward and has
   the model write the outcome texts; re-run all gates.

## Phase 4 — Interface in the story's language

- UI strings layer: built-in English + Russian dictionaries; generator adds a `ui` block of
  translated labels to each story for any other language; English fallback for old stories.
- Translate character creation (intro, attribute names/descriptions), all buttons, roll
  labels, outcome/log messages, end screens, share texts and the feedback form.
- Backfill script for existing non-English stories.

## Phase 5 — Story-review agent

- `narrative_review.py`: walks every choice → destination and asks a cheap model (Haiku 4.5 /
  free Gemini) whether the scene follows from the choice and the previous scene, and whether
  anything is used before it's introduced.
- Runs as the 4th gate inside `create_story`, feeding findings into the repair loop; its cost
  is logged to the monthly budget ledger. Also usable standalone to audit existing stories.

## Backlog

- **Streamlit `use_container_width` → `width="stretch"`**: deprecated and being removed
  release by release; CI (latest Streamlit) will go red the day it breaks — migrate before then.

- **Vocabulary helper** (deferred): per-location glossary written at generation time, word
  look-up, personal word list with story examples, copy / CSV (Anki) export.

## Owner to-dos

- CI/CD one-time setup (`DEPLOY.md`): compose plugin on the droplet, deploy key, GitHub secrets.

- Create the feedback Telegram bot (@BotFather → token) and get your chat ID; put both in `.env`.
- Buy a domain → point it at GitHub Pages (landing) and a `play.` subdomain at the droplet;
  then set `QUEST_PUBLIC_URL` and repoint the landing page's Play button.
- Enable GitHub Pages: Settings → Pages → branch `master`, folder `/docs`.
- Uncomment `github:` in `.github/FUNDING.yml` once GitHub Sponsors is approved.
- Run `compare_models.py` on the droplet and set `QUEST_GEN_MODEL` to the winner.
