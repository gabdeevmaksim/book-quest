---
name: cyoa-generator
description: Generates a complete, playable JSON Choose-Your-Own-Adventure (CYOA) RPG from any user theme and difficulty, then automatically validates and balance-checks it so it is guaranteed to run correctly in the Quest Book engine (app.py). Use whenever a user wants to create, generate, or set up a new story/adventure from a theme.
---

# CYOA Generator

Turn a one-line theme into a finished, balanced, **validated** `story.json` that the
Quest Book engine (`app.py`) can run immediately. This skill is a universal tool: the
player supplies a theme (and optionally a difficulty), and you generate, validate, and
balance-check the story end to end before handing it back.

## Inputs to collect

1. **Theme** — any setting (e.g. "Cyberpunk Tokyo", "Haunted lighthouse", "Norse myth").
2. **Difficulty** — `easy`, `normal`, or `hard`. Default to **normal** if unspecified.
   Difficulty controls starting HP, check difficulty (DCs), fail damage, and monster
   strength — see the preset table below.
3. *(optional)* Desired length — default 12–16 locations, 3–5 endings.

If the user gave a theme in their message, don't re-ask — proceed. Only ask if the
theme is missing.

## Mandatory workflow — DO ALL FIVE STEPS

Stories live in the **`stories/`** library — one `*.json` per adventure. Save new stories
there as `stories/<slug>.json` (slug = lowercase title, e.g. `stories/pirate_ghost_ship.json`).
The app's main-screen gallery auto-discovers every file in `stories/`.

1. **Generate** a complete story to `stories/<slug>.json` following the schema + difficulty preset.
2. **Validate** link/reachability integrity:
   ```bash
   python3 cyoa-skills/cyoa-validator/scripts/validate_story.py stories/<slug>.json
   ```
   Fix any issues (edit the JSON, or `--fix` for auto-fixable graph issues) and re-validate
   until it prints **"No issues found"**.
3. **Coherence & pre-history** — the map must read like a real place and open with real backstory:
   ```bash
   python3 cyoa-skills/cyoa-validator/scripts/coherence_report.py stories/<slug>.json
   ```
   Address every REVIEW item until it prints **"COHERENCE: OK"** (or you can justify a flag,
   e.g. a deliberate hub). Especially: kill aimless free-movement loops, keep the backtrack
   ratio low, write a real `prologue`, give every check and monster its `success_text` +
   `fail_text`, and include exactly the hinted dead ends the difficulty asks for.
4. **Balance-check** against the requested difficulty:
   ```bash
   python3 playtest.py stories/<slug>.json <difficulty>
   ```
   Tune HP / DCs / fail_damage toward the preset and re-run until it prints **PASS**.
5. **Story review** (continuity, if a model key is available):
   ```bash
   python3 narrative_review.py stories/<slug>.json
   ```
   Fix every **major** issue (transitions that don't follow, outcome texts that clash with the
   next scene, things used before they're introduced, contradictions, endings that don't pay
   off) and re-run until it prints `REVIEW: OK`. Minor issues are optional.
6. **Report**: confirm it is valid + coherent + balanced + reviewed; it now appears in the
   library on the main screen (`streamlit run app.py`).

Never hand back a story that has not passed steps 2, 3 and 4 (and 5 when a key is available).

**Continuity rules the review checks** — write with them in mind from the start: every
scene must follow from the choice that leads to it AND make sense for every other way in
(scenes reached from several places can't assume one route); both outcome texts of a
challenge must lead naturally into the same next scene; never refer to a person, object or
place as already known before the player can have met it on that path; keep facts consistent
(who is alive, time of day, what the hero carries); victories pay off the goal.

> The in-app **"Create a New Story"** page runs the generate → validate → balance pipeline
> automatically using this spec as its system prompt. For the most polished result (coherence
> pass + repair loop), use the **story-smith** agent (`.claude/agents/story-smith.md`), which
> runs all five steps and iterates until every gate is green.

## Story schema (current engine — keep in sync with app.py)

```jsonc
{
  "title": "Story Title",
  "theme": "The theme",
  "difficulty": "normal",                 // metadata; record what you targeted
  "language": "English",                  // language of ALL player-facing text (default English)
  "language_level": "C2",                 // CEFR level of the prose: A1|A2|B1|B2|C1|C2 (default C2/native)
  "goal": "One sentence describing what winning looks like.",
  "prologue": "3-6 sentences of pre-history, shown on the character screen before play: who you are, the world, the inciting incident, and the stakes.",
  "character_template": { "health": 18, "strength": 10, "agility": 10, "stamina": 10 },

  "items": {                              // OPTIONAL. Every item MUST have a real role.
    "lantern":  { "name": "Oil Lantern", "icon": "🏮",
                  "description": "Lights the dark.",
                  "use": { "heal": 8 } },                 // consumable: Use button heals
    "charm":    { "name": "Bone Charm", "icon": "🦴",
                  "description": "+3 to Agility checks in the catacombs." },
    "iron_key": { "name": "Iron Key",  "icon": "🗝️",
                  "description": "Opens the sealed gate." }
  },

  "start_location_id": "start",
  "locations": {
    "start": {
      "description": "Rich 2–4 sentence scene-setting prose. Rotten planks cover the old well.",
      "is_end": false,
      "loot": ["lantern"],               // OPTIONAL: items granted on first visit
      "choices": [
        { "text": "Take the stairs down to the hall", "target_id": "hall" },

        { "text": "Shoulder the warped cellar door",
          "target_id": "vault",
          "condition": {                 // ONE roll: roll(dice)+attribute(+bonus) >= check_value
            "attribute": "strength",     // must be strength | agility | stamina
            "check_value": 10,
            "dice_type": "1d6",
            "fail_damage": 5,            // HP lost on failure — the hero STILL gets through
            "success_text": "The door bursts inward on the second heave.",
            "fail_text": "The door gives way — and so does something in your shoulder. You stagger into the vault.",
            "item_bonus": { "item": "charm", "bonus": 3 }   // OPTIONAL: +bonus if item held
          },
          "gives_item": "iron_key",      // OPTIONAL: grant item(s) on this choice (string or list)
          "requires_item": "lantern",    // OPTIONAL: choice hidden unless item held
          "heals": 6,                    // OPTIONAL: restore HP when taken (rarely needed; prefer item "use")
          "consumes_item": "lantern"     // OPTIONAL: remove item(s) when taken
        },

        { "text": "Climb down the old well",   // a DEAD END (normal/hard only — see "Dead ends")
          "target_id": "well_shaft",
          "trap_hint": "Rotten planks cover the old well"   // exact phrase from this description
        }
      ],
      "monster": {                       // OPTIONAL: one roll decides the whole encounter
        "name": "Cellar Ghoul",
        "strength": 10,                  // the DC: player needs roll(dice)+attribute >= this
        "fail_damage": 6,                // HP lost if the roll fails — the hero still gets past
        "dice_type": "1d6",
        "attribute": "strength",         // which stat the player fights with (default strength)
        "success_text": "Your lantern-swing drops the ghoul in a heap of rags and bone.",
        "fail_text": "The ghoul's claws open your forearm before you shove it down the steps and run past."
      }
    },
    "win": { "description": "You made it.", "is_end": true, "is_victory": true, "choices": [] }
  }
}
```

### Field rules the engine relies on
- **Every challenge is passable.** A check (`condition`) or a monster is resolved by ONE roll.
  Success → the hero gets through cleanly. Failure → the hero STILL gets through to the same
  destination (and receives the choice's items), but loses `fail_damage` HP. Nothing blocks
  or loops; a run ends early only when HP reaches 0. **Never use `fail_target`** — it is
  retired (the engine only honours it in old stories).
- Every `condition` and every `monster` MUST have `success_text` and `fail_text` (see
  "Outcome texts" below). The game shows the right one right after the roll.
- A **monster** uses only `name`, `strength` (DC), `fail_damage`, `dice_type`, `attribute`,
  `success_text`, `fail_text`. It does **not** use `health`/`agility` — don't add them.
- During a monster encounter, the **Fight** button and any `"is_flee": true` choices are
  shown. A flee choice is an **alternative approach** (sneak past, outrun, bluff) with its own
  `condition`, outcome texts and `target_id`. After the encounter — won or lost — the
  location's non-flee choices appear, so **every monster location needs at least one
  non-flee onward choice**.
- Endings are locations with `"is_end": true`. Add `"is_victory": false` for a grim/dead
  ending; default is a victory. Endings have an empty `choices: []`.
- `trap_hint` on a choice marks the entrance to a dead-end branch (see "Dead ends").

## Outcome texts — realistic, and matched to the approach

Each check and monster carries two short texts (1–2 sentences, in the story's `language`):
- `success_text` — how the hero gets through cleanly.
- `fail_text` — the hero **still gets through**, and the text says **what it cost**: a
  concrete, physically plausible injury that fits the **attribute and method** used.
  Scale how bad it sounds with `fail_damage`.

Offer different approaches to the same obstacle as separate choices, each with its own
attribute and consequence. A locked door, for example:
- *strength* — "Shoulder the door": fail → "the door gives way, but your shoulder takes the blow".
- *agility* — "Squeeze through the gap in the planks": fail → "a splinter tears a gash along your arm".
- *stamina* — "Hammer at the hinges until they give": fail → "it takes so long your knuckles are
  raw and your arms shake" (exhaustion).
Monsters likewise: fight (strength) → claws, bites, a cracked rib; slip past (agility) → a graze
as it lunges; outlast it (stamina) → you're winded and bruised. Never write a fail text in which
the hero is stopped, turned back or captured — failure always continues.

## Difficulty presets (calibrated for the fail-forward rules)

Dice math: a stat is rolled as **2d6** (range 2–12, avg 7); checks add **1d6** (avg 3.5),
so an average total is ~10.5. Pass odds at attribute **7** (players usually route to a
stronger stat, so real odds run a little higher):

`DC 8→100% · 9→83% · 10→67% · 11→50% · 12→33% · 13→17% · 14+→0%`

A DC of 13–14 is a near-certain failure without an item bonus — it can't block anyone any
more, it just hurts. A +2/+3 item turns it into a fair roll (DC 13 with +3 → 67%), which is
what makes items worth hunting.

**Where the stakes come from.** Since nobody is ever blocked, the only way to lose is
accumulated damage (or a dead end). So danger must sit on the **routes to victory**: every
route from the start to a victory must pass through the number of challenges below. Free
(no-check) choices are for movement and side content — they must not let a careful player
walk around all the danger.

| Difficulty | `health` | Check DC (travel / climactic) | fail_damage (minor / climactic) | Monster DC / fail_damage | Challenges on every route to victory | Heals |
|---|---|---|---|---|---|---|
| **easy**   | 22–28 | 7–8 / 9      | 3 / 5     | 8–10 / 5–8   | 3–5 | generous |
| **normal** | 18–22 | 8–9 / 10–11  | 4 / 6     | 9–11 / 6–9   | 5–7 | one heal item per long route |
| **hard**   | 16–20 | 9–10 / 11–12 | 5 / 7     | 10–12 / 8–10 | 7–9 | scarce |

Target outcomes `playtest.py` checks for: **easy** ≈ cautious win ≥93%, heroic death ≤12%;
**normal** ≈ cautious win 85–99%, heroic death 12–35%; **hard** ≈ cautious win 60–88%,
heroic death 30–75% (still beatable). The *cautious* player heeds trap hints; the *heroic*
player fights everything and ignores hints.

## Dead ends ("traps") — wrong decisions, always hinted

On **normal** and **hard**, some wrong decisions lead into a situation the hero cannot get
out of. These are **dead-end branches**:
- The entrance is a choice with `"trap_hint": "<phrase>"`. The phrase must appear
  **verbatim** in that location's `description` (or the choice text) and must **foreshadow**
  the danger, so a careful reader can avoid it ("the ice groans under every step", "the
  planks look rotten", "the smuggler won't meet your eyes").
- The branch is **played out** over **2–3 locations** (the hero realises, struggles, it gets
  worse) before a non-victory ending (`"is_end": true, "is_victory": false`). Never jump
  straight from a normal choice to a bad ending, and no location in the branch may lead back
  to a victory.
- **How many:** easy **0** · normal **1** (or 1–2 above 14 locations) · hard **2–4**,
  growing with length (2 up to 16 locations, 3 up to 21, 4 beyond). The coherence gate checks
  the count, that each branch is a real dead end, and that each hint is present.
- **Easy** has no dead ends at all: every location must still be able to reach a victory.
  (Easy mode also gives the player a "Go back" button.)

## Design rules (these prevent the bugs the validator/playtester catch)

- **Reachable & winnable**: every location must be reachable from start, and every
  location must have a path to some `is_end`. (The validator enforces both.)
- **No dead items**: every item must be *required* by a choice (gate), grant an
  `item_bonus`, and/or have a `use` effect. Never add purely decorative items.
- **Heals must be real**: if choice text promises HP ("+8 HP", "patch your wounds"),
  back it with `heals` or an item `use:{heal:N}`. Never imply healing without the mechanic.
- **No untagged dead ends**: apart from hinted traps, every location must be able to reach a
  victory.
- **Obtainable gates**: an item named in `requires_item` must be grantable (loot or
  `gives_item`) on an earlier, reachable path.
- **Spread the stats**: use all three of strength/agility/stamina across checks so no
  single dump-stat trivializes or bricks a run.
- **Ground every item in the narrative**: an item must never appear out of nowhere. The
  location description (or the choice text that grants it) MUST mention the object —
  "a vintage jersey hangs in the locker", "you pry the iron key from the lock". Prefer an
  explicit pick-up choice with `gives_item` ("Take the lantern from the hook") over silent
  `loot`; if you do use `loot`, the description must introduce the object. The coherence
  gate flags ungrounded grants.
- **One grant per path**: never let the same item be collected twice on a single playthrough.
  Granting it on two *mutually exclusive* branches is fine; two grants on one reachable
  path is a flag.

### Connectivity & opening (what makes a story feel finished, not chaotic)
- **Coherent map**: design locations as a real place with regions that connect logically.
  Every choice's destination must follow from its text — no random teleports. Aim for ~2–4
  choices per location; never exceed 6.
- **Branch, don't railroad**: most non-ending locations need **2–3 meaningful choices** that
  lead to *different* outcomes. At most ~⅓ may have a single choice, and never more than 2–3
  single-choice locations in a row. The coherence gate fails corridors (>40% single-choice
  locations, avg <1.6 choices, or a chain of 4+).
- **Forward motion**: most choices should advance the story. Keep backtracking low
  (`coherence_report.py` flags >35%). A hub is fine *only* if each spoke has real content and
  you cannot circle a set of rooms endlessly at no cost (no aimless free-movement loops).
- **Critical path + side content**: provide a clear spine from start to a victory, with
  optional branches — not a soup of cross-links.
- **Real pre-history**: always write a `prologue` (3–6 sentences) that drops the player into
  the world — who they are, what just happened, why it matters — then orient them in the
  start location's opening scene. Thin/missing pre-history is a coherence REVIEW failure.

## Language & language level

Stories can be written in **any language**, at a target **CEFR level** — useful for language
learners. Two top-level fields record the choice: `language` (e.g. "Italian") and
`language_level` (A1–C2). Rules:

- ALL player-facing text — title, goal, prologue, descriptions, choice texts, item names,
  item descriptions, monster names, ending texts — is written in `language`. JSON keys,
  location ids, and item ids stay in English (`snake_case`).
- Match the prose to the CEFR level: **A1/A2** — present tense, short sentences (max ~8–10
  words), only high-frequency vocabulary, repeat key words instead of using synonyms;
  **B1/B2** — natural everyday narrative, common idioms allowed, moderate sentence length;
  **C1/C2** — full native richness, atmosphere, idiom, and subtext.
- Keep descriptions at lower levels *shorter* (1–2 simple sentences) rather than padding to
  the usual 2–4; the story should stay vivid through concrete nouns and actions.
- Default when unspecified: `language: "English"`, `language_level: "C2"`.

## Resources
- `references/sample_story.json` — a small, clean, schema-complete example (normal difficulty).
- Correctness: `cyoa-skills/cyoa-validator/scripts/validate_story.py`
- Coherence / pre-history: `cyoa-skills/cyoa-validator/scripts/coherence_report.py`
- Balance: `playtest.py` (repo root) — `python3 playtest.py <story> [easy|normal|hard]`
- Orchestrator agent: `.claude/agents/story-smith.md` (runs all gates with a repair loop).
