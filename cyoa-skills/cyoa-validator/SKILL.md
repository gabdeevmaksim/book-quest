---
name: cyoa-validator
description: Validates a CYOA story JSON file for consistency, reachability, and completeness. Ensures all choices lead to existing locations and that no dead-ends exist.
---

# CYOA Validator

This skill ensures that a generated CYOA story is logically sound and playable from start to finish.

## Workflow

1. **Load Story**: Load the `story.json` file from the current directory.
2. **Run Validation**: Execute the validation script to check for logical errors.
3. **Report Issues**: Display a summary of any broken links, unreachable locations, or dead-ends.

## Checks Performed

- **Schema Validation**: Ensures the JSON structure matches the required format.
- **Link Integrity**: Verifies that every `target_id` in every choice exists in the `locations` object.
- **Reachability**: Checks if every location can be reached starting from the `start_location_id`.
- **Termination**: Ensures that every path from the start eventually reaches a location marked as `is_end: true`.
- **Attribute Consistency**: Validates that all attribute checks refer to valid character attributes.

## Usage

Check correctness (links, reachability, can-reach-an-ending):
```bash
python3 scripts/validate_story.py story.json
```

Check connectivity & pre-history (flags chaotic/disconnected maps and thin openings):
```bash
python3 scripts/coherence_report.py story.json
```
