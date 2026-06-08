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

## Mandatory workflow — DO ALL FOUR STEPS

Stories live in the **`stories/`** library — one `*.json` per adventure. Save new stories
there as `stories/<slug>.json` (slug = lowercase title, e.g. `stories/pirate_ghost_ship.json`).
The app's main-screen gallery auto-discovers every file in `stories/`.

1. **Generate** a complete story to `stories/<slug>.json` following the schema + difficulty preset.
2. **Validate** link/reachability integrity:
   ```bash
   python3 cyoa-skills/cyoa-validator/scripts/validate_story.py stories/<slug>.json
   ```
   If it reports issues, fix them (edit the JSON, or re-run with `--fix` for
   auto-fixable graph issues) and re-validate until it prints **"No issues found"**.
3. **Balance-check** against the requested difficulty:
   ```bash
   python3 playtest.py stories/<slug>.json <difficulty>
   ```
   This runs 20k simulated playthroughs per playstyle and prints a PASS/ADJUST verdict.
   If it says ADJUST, nudge HP / DCs / fail_damage toward the preset and re-run.
4. **Report**: confirm it is valid + balanced and tell the user it now appears in the
   library on the main screen (`streamlit run app.py`).

Never hand back a story that has not passed steps 2 and 3.

> The in-app **"Create a New Story"** page runs this exact pipeline automatically
> (generate → validate → balance-check → save to `stories/`) using this spec as its
> system prompt, so keep this file authoritative.

## Story schema (current engine — keep in sync with app.py)

```jsonc
{
  "title": "Story Title",
  "theme": "The theme",
  "difficulty": "normal",                 // metadata; record what you targeted
  "goal": "One sentence describing what winning looks like.",
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
      "description": "Rich 2–4 sentence scene-setting prose.",
      "is_end": false,
      "loot": ["lantern"],               // OPTIONAL: items granted on first visit
      "choices": [
        { "text": "Safe option (no risk)", "target_id": "hall" },

        { "text": "Risky option",
          "target_id": "vault",
          "condition": {                 // triggers a dice roll: roll(dice)+attribute(+bonus) >= check_value
            "attribute": "agility",      // must be strength | agility | stamina
            "check_value": 15,
            "dice_type": "2d6",
            "fail_damage": 5,            // HP lost on failure
            "fail_target": "pit",        // OPTIONAL: where failure sends you (omit = stay & retry)
            "item_bonus": { "item": "charm", "bonus": 3 }   // OPTIONAL: +bonus if item held
          },
          "gives_item": "iron_key",      // OPTIONAL: grant item(s) on this choice (string or list)
          "requires_item": "lantern",    // OPTIONAL: choice hidden unless item held
          "heals": 6,                    // OPTIONAL: restore HP when taken (rarely needed; prefer item "use")
          "consumes_item": "lantern"     // OPTIONAL: remove item(s) when taken
        }
      ],
      "monster": {                       // OPTIONAL: blocks the location until defeated
        "name": "Cellar Ghoul",
        "strength": 15,                  // the DC: player needs roll(dice)+attribute >= this
        "fail_damage": 6,                // HP lost per failed attempt
        "dice_type": "2d6",
        "attribute": "strength"          // which stat the player fights with (default strength)
      }
    },
    "win": { "description": "You made it.", "is_end": true, "is_victory": true, "choices": [] }
  }
}
```

### Field rules the engine relies on
- A **monster** uses only `name`, `strength` (DC), `fail_damage`, `dice_type`, `attribute`.
  It does **not** use `health`/`agility` — don't add them. Always include `fail_damage`.
- During a monster encounter, only the **Fight** button and any choice with
  `"is_flee": true` are shown. Non-flee choices appear **after** the monster is defeated
  (use them as the "after the fight" continuation). A flee choice may carry its own
  `condition` and `target_id` to act as an alternate/stealth route.
- Endings are locations with `"is_end": true`. Add `"is_victory": false` for a grim/dead
  ending; default is a victory. Endings have an empty `choices: []`.
- `fail_target` and `item_bonus` may live inside `condition`; `fail_target` may also sit
  on the choice. The engine and validator accept both.

## Difficulty presets (derived from playtested tuning)

Dice math: a stat is rolled as **3d6** (range 3–18, avg ~10.5); checks add **2d6** (avg 7),
so an average total is ~17.5. Pass odds at attribute **10** (players usually route to a
stronger stat, so real odds run a little higher):

`DC 12→100% · 13→97% · 14→92% · 15→83% · 16→72% · 17→58% · 18→42% · 19→28%`

| Difficulty | `health` | Travel-check DC | Climactic DC | fail_damage (minor / climactic) | Monster STR-DC / fail | Healing & safety valves |
|---|---|---|---|---|---|---|
| **easy**   | 26–30 | 10–12 | 12–14 | 2 / 3   | 11–13 / 3–4 | generous heal items; many no-check options |
| **normal** | 16–20 | 12–14 | 14–16 | 3–4 / 5–6 | 14–16 / 5–7 | one heal item per long route; add retreats |
| **hard**   | 12–14 | 13–15 | 16–18 | 4–5 / 7–9 | 16–18 / 8–10 | scarce heals; few safe options |

Target outcomes `playtest.py` checks for: **easy** ≈ cautious win ≥93%, heroic death <12%;
**normal** ≈ cautious win 85–99%, heroic death 12–35%; **hard** ≈ cautious win 60–88%,
heroic death ≥30% (still beatable).

## Design rules (these prevent the bugs the validator/playtester catch)

- **Reachable & winnable**: every location must be reachable from start, and every
  location must have a path to some `is_end`. (The validator enforces both.)
- **No dead items**: every item must be *required* by a choice (gate), grant an
  `item_bonus`, and/or have a `use` effect. Never add purely decorative items.
- **Heals must be real**: if choice text promises HP ("+8 HP", "patch your wounds"),
  back it with `heals` or an item `use:{heal:N}`. Never imply healing without the mechanic.
- **No free-retry**: never use `fail_damage: 0` together with no `fail_target` — that's a
  consequence-free infinite retry. Give it a cost or a `fail_target`.
- **No hard locks**: any check or monster a minimum-stat (3) hero could never pass
  (`3 + max(dice) < DC`) MUST have an alternative route or a flee. Bosses always get a
  flee and/or an alternate-attribute route.
- **Safety valves**: from any committed multi-room gauntlet, include a retreat choice so a
  weak hero can back out instead of dying with no options.
- **Obtainable gates**: an item named in `requires_item` must be grantable (loot or
  `gives_item`) on an earlier, reachable path.
- **Spread the stats**: use all three of strength/agility/stamina across checks so no
  single dump-stat trivializes or bricks a run.

## Resources
- `references/sample_story.json` — a small, clean, schema-complete example (normal difficulty).
- Validator: `cyoa-skills/cyoa-validator/scripts/validate_story.py`
- Balance harness: `playtest.py` (repo root) — `python3 playtest.py story.json [easy|normal|hard]`
