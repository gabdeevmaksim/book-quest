"""
story_engine.py — Streamlit-free core for generating and vetting Quest Book stories.

Shared by:
  - app.py          → the in-app "Create a New Story" page
  - story_agent.py  → the standalone CLI orchestrator (runs on any server, free Gemini key)

This module has NO Streamlit dependency, so the agent can run with only `google-genai`
installed (no need for streamlit on a generation-only server). It holds:
  - provider config (Google Gemini by default; Anthropic optional)
  - the spec/system prompt + user prompt builders
  - the model call (with retry/backoff) and JSON extraction
  - correctness validation (reuses cyoa-validator) and the balance gate (runs playtest.py)
  - story library IO helpers

Run from the repository root (paths below are repo-relative).
"""
import os
import re
import json
import time
import glob
import tempfile
import subprocess
from functools import lru_cache

def _load_dotenv(path=".env"):
    """Minimal .env loader (no dependency) so the CLI works outside docker-compose.
    Reads KEY=VALUE lines (also `export KEY=VALUE`); never overrides variables that
    are already set in the environment."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_dotenv()

# ── config ─────────────────────────────────────────────────────────────────────
STORIES_DIR    = os.environ.get("QUEST_STORIES_DIR", "stories")
VALIDATOR_PATH = os.path.join("cyoa-skills", "cyoa-validator", "scripts", "validate_story.py")
COHERENCE_PATH = os.path.join("cyoa-skills", "cyoa-validator", "scripts", "coherence_report.py")
PLAYTEST_PATH  = "playtest.py"
GENERATOR_SPEC = os.path.join("cyoa-skills", "cyoa-generator", "SKILL.md")
DIFFICULTIES   = ["easy", "normal", "hard"]
GEN_MAX_TOKENS = 16000

DEFAULT_MODELS = {"google": "gemini-3.5-flash", "anthropic": "claude-sonnet-4-6"}
# Fallback chains: if a model hits its (free-tier) limit, the agent advances to the next one.
# Override with QUEST_GEN_MODELS="m1,m2,..." or pin a single one with QUEST_GEN_MODEL="m".
DEFAULT_MODEL_CHAINS = {
    "google":    ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
    "anthropic": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
}
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


def gen_models(provider):
    """Ordered fallback chain of models to try for this provider.
    QUEST_GEN_MODELS='m1,m2,...' overrides the chain; QUEST_GEN_MODEL='m' pins a single model."""
    chain = os.environ.get("QUEST_GEN_MODELS", "").strip()
    if chain:
        return [m.strip() for m in chain.split(",") if m.strip()]
    single = os.environ.get("QUEST_GEN_MODEL", "").strip()
    if single:
        return [single]
    return list(DEFAULT_MODEL_CHAINS.get(provider, [DEFAULT_MODELS.get(provider, "")]))


def env_api_key(provider):
    if provider == "google":
        return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""
    return os.environ.get("ANTHROPIC_API_KEY") or ""


# ── story library IO ─────────────────────────────────────────────────────────
def list_stories():
    """Metadata for every story in the library (stories/*.json)."""
    paths = sorted(p for p in glob.glob(os.path.join(STORIES_DIR, "*.json"))
                   if not os.path.basename(p).startswith((".", "_")))
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
                "draft": bool(d.get("draft")),
                "language": d.get("language", ""),
                "language_level": d.get("language_level", ""),
            })
        except Exception as e:
            out.append({"path": p, "title": os.path.basename(p), "error": str(e),
                        "theme": "", "difficulty": "", "goal": "", "n": 0, "draft": False,
                        "language": "", "language_level": ""})
    return out


def load_story_file(path):
    with open(path, "r") as f:
        return json.load(f)


def slugify(s):
    # \w keeps Unicode letters/digits, so non-Latin titles (e.g. Russian) get real slugs
    # instead of collapsing to the "story" fallback
    s = re.sub(r"[^\w]+", "_", (s or "").lower()).strip("_")
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


def push_story_to_git(path):
    """Commit a newly saved story and push it to the remote. Returns (ok, detail) and never
    raises — `detail` carries the exact git error so callers can SHOW it instead of hiding it.

    Headless/Docker friendly:
    - `safe.directory=*` (bind-mounted repos owned by another uid),
    - identity fallback when user.name/email are unset (override with QUEST_GIT_NAME/EMAIL),
    - HTTPS push auth via QUEST_GIT_TOKEN or GITHUB_TOKEN (a GitHub PAT) when no credential
      helper is available."""
    import subprocess

    def run(args):
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=60)
        except Exception as e:  # git missing, timeout, …
            return subprocess.CompletedProcess(args, 255, "", str(e))

    token = os.environ.get("QUEST_GIT_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""

    def redact(s):
        return (s or "").replace(token, "***") if token else (s or "")

    git = ["git", "-c", "safe.directory=*"]
    if not run(["git", "config", "user.name"]).stdout.strip():
        git += ["-c", "user.name=" + os.environ.get("QUEST_GIT_NAME", "Quest Book")]
    if not run(["git", "config", "user.email"]).stdout.strip():
        git += ["-c", "user.email=" + os.environ.get("QUEST_GIT_EMAIL", "quest-book@localhost")]

    for stage, cmd in [("add", git + ["add", "-f", path]),
                       ("commit", git + ["commit", "-m", f"Add story: {os.path.basename(path)}",
                                         "--", path])]:
        r = run(cmd)
        if r.returncode != 0:
            return False, f"git {stage} failed: {redact(r.stderr or r.stdout).strip()[:300]}"

    push_cmd = git + ["push"]
    if token:
        url = run(["git", "remote", "get-url", "--push", "origin"]).stdout.strip()
        if url.startswith("https://") and "@" not in url:
            push_cmd = git + ["push",
                              url.replace("https://", f"https://x-access-token:{token}@", 1),
                              "HEAD"]
    r = run(push_cmd)
    if r.returncode != 0:
        return False, ("committed locally, but git push failed: "
                       + redact(r.stderr or r.stdout).strip()[:300])
    return True, "committed and pushed to the remote"


# ── optional S3-compatible story storage (AWS S3 / Cloudflare R2 / Backblaze B2 / MinIO) ──
# Enable by setting QUEST_S3_BUCKET. The bucket is the durable, cross-machine store; the
# local stories/ folder acts as a cache: new stories are uploaded on save, and the app
# pulls missing/newer stories down at startup. Credentials use the standard AWS env vars
# (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) or any boto3 credential source.
#   QUEST_S3_BUCKET    bucket name (setting this turns the feature on)
#   QUEST_S3_ENDPOINT  custom endpoint for R2/B2/MinIO, e.g. https://<acct>.r2.cloudflarestorage.com
#   QUEST_S3_REGION    region (optional; e.g. "auto" for R2)
#   QUEST_S3_PREFIX    key prefix inside the bucket (default "stories/")

def s3_enabled():
    return bool(os.environ.get("QUEST_S3_BUCKET"))


@lru_cache(maxsize=1)
def _s3_client():
    import boto3   # lazy: only needed when QUEST_S3_BUCKET is set
    kw = {}
    if os.environ.get("QUEST_S3_ENDPOINT"):
        kw["endpoint_url"] = os.environ["QUEST_S3_ENDPOINT"]
    if os.environ.get("QUEST_S3_REGION"):
        kw["region_name"] = os.environ["QUEST_S3_REGION"]
    return boto3.client("s3", **kw)


def _s3_conf():
    return (os.environ.get("QUEST_S3_BUCKET", ""),
            os.environ.get("QUEST_S3_PREFIX", "stories/").strip("/") + "/")


def push_story_to_s3(path, client=None):
    """Upload one story file to the bucket. Returns (ok, detail); never raises."""
    if not s3_enabled():
        return False, "S3 storage not configured (set QUEST_S3_BUCKET)"
    bucket, prefix = _s3_conf()
    key = prefix + os.path.basename(path)
    try:
        client = client or _s3_client()
        client.upload_file(path, bucket, key, ExtraArgs={"ContentType": "application/json"})
        return True, f"uploaded to s3://{bucket}/{key}"
    except ImportError:
        return False, "boto3 isn't installed — pip install boto3"
    except Exception as e:
        return False, f"S3 upload failed: {str(e)[:300]}"


def sync_stories_from_s3(client=None):
    """Download stories that exist in the bucket but are missing (or newer) locally.
    Returns (n_downloaded, errors); never raises. The bucket wins on conflicts."""
    if not s3_enabled():
        return 0, []
    bucket, prefix = _s3_conf()
    n, errors = 0, []
    try:
        client = client or _s3_client()
        os.makedirs(STORIES_DIR, exist_ok=True)
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                name = os.path.basename(obj["Key"])
                if not name.endswith(".json"):
                    continue
                local = os.path.join(STORIES_DIR, name)
                if (not os.path.exists(local)
                        or obj["LastModified"].timestamp() > os.path.getmtime(local) + 1):
                    try:
                        client.download_file(bucket, obj["Key"], local)
                        n += 1
                    except Exception as e:
                        errors.append(f"{name}: {str(e)[:200]}")
    except ImportError:
        errors.append("boto3 isn't installed — pip install boto3")
    except Exception as e:
        errors.append(f"S3 sync failed: {str(e)[:300]}")
    return n, errors


def seed_s3_from_local(client=None):
    """One-time migration helper: upload every local story the bucket doesn't have yet.
    Returns (n_uploaded, errors); never raises."""
    if not s3_enabled():
        return 0, ["S3 storage not configured (set QUEST_S3_BUCKET)"]
    bucket, prefix = _s3_conf()
    n, errors = 0, []
    try:
        client = client or _s3_client()
        have = set()
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            have |= {os.path.basename(o["Key"]) for o in page.get("Contents", [])}
        for p in glob.glob(os.path.join(STORIES_DIR, "*.json")):
            if os.path.basename(p) not in have:
                ok, detail = push_story_to_s3(p, client=client)
                if ok:
                    n += 1
                else:
                    errors.append(detail)
    except ImportError:
        errors.append("boto3 isn't installed — pip install boto3")
    except Exception as e:
        errors.append(f"S3 seed failed: {str(e)[:300]}")
    return n, errors


# ── gates: correctness + balance ───────────────────────────────────────────────
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


def _run(cmd, timeout=200):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def coherence_check(path):
    """Run coherence_report.py. Returns (ok_bool, [REVIEW item lines])."""
    try:
        r = _run(["python3", COHERENCE_PATH, path])
        out = r.stdout
        ok = "COHERENCE: OK" in out
        review = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("[")]
        return ok, review
    except Exception as e:
        return False, [f"(coherence check failed to run: {e})"]


def balance_check(path, difficulty):
    """Run playtest.py as a balance gate. Returns (verdict, [metric/hint lines])."""
    try:
        r = _run(["python3", PLAYTEST_PATH, path, difficulty])
        out = r.stdout
        verdict = "PASS" if ">>> PASS" in out else ("ADJUST" if "ADJUST" in out else "—")
        lines = [ln.strip() for ln in out.splitlines()
                 if ln.strip().startswith(("cautious win", "heroic death", "hint:"))]
        return verdict, lines
    except Exception as e:
        return "—", [f"(balance check unavailable: {e})"]


# ── model access ────────────────────────────────────────────────────────────────
def extract_json(text):
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


def call_model(provider, model, system, messages, api_key):
    """One completion from the chosen provider. messages: [{'role':'user'|'assistant','content'}].
    Returns the model's text. Raises ImportError if the provider SDK isn't installed.
    Retries with exponential backoff on 503 / rate-limit errors (free-tier friendly)."""
    retryable = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "rate_limit", "overloaded")
    max_retries, delay = 2, 4   # short per-model backoff; call_with_fallback switches models next
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
            if attempt < max_retries and any(k in str(e) for k in retryable):
                time.sleep(delay)
                delay *= 2
                continue
            raise


def call_with_fallback(provider, models, system, messages, api_key, log=None):
    """Try each model in order; on ANY failure advance to the next one. This is what makes the
    agent survive free-tier limits: when a model's quota is exhausted (or it's unavailable), the
    next model in the chain takes over. Returns (text, model_used); raises only if all models fail."""
    errors = []
    for i, model in enumerate(models):
        try:
            return call_model(provider, model, system, messages, api_key), model
        except Exception as e:
            errors.append(f"{model}: {str(e)[:200]}")
            if i < len(models) - 1:
                if log:
                    log(f"    ! {model} unavailable ({str(e)[:70]}…) — switching to {models[i + 1]}")
                continue
            raise RuntimeError("all configured models failed:\n  " + "\n  ".join(errors)) from e
    raise RuntimeError("no models configured")


CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]


def _language_clause(language, language_level):
    """Prompt fragment enforcing the story language and CEFR level."""
    language = (language or "English").strip() or "English"
    level = (language_level or "C2").strip().upper()
    if level not in CEFR_LEVELS:
        level = "C2"
    style = {
        "A1": "very short, simple sentences (max ~8 words), present tense only, only the most "
              "common everyday words, repeat key words instead of using synonyms",
        "A2": "short, simple sentences, mostly present tense, high-frequency vocabulary, "
              "no idioms or rare words",
        "B1": "clear everyday narrative, moderate sentence length, common idioms only",
        "B2": "natural fluent narrative, varied sentence structure, everyday idioms allowed",
        "C1": "rich, nuanced prose with idiom and atmosphere",
        "C2": "full native richness — idiom, subtext, and atmosphere",
    }[level]
    return (
        f'Language: write ALL player-facing text (title, goal, prologue, location descriptions, '
        f'choice texts, item names and descriptions, monster names) in {language} at CEFR level '
        f'{level}: {style}. Keep JSON keys, location ids and item ids in English snake_case. '
        f'Set the top-level fields "language": "{language}" and "language_level": "{level}".\n'
    )


def build_prompts(theme, difficulty, length, title_hint="", language="English", language_level="C2"):
    """Return (system, user) prompts. The spec file is the authoritative system prompt."""
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
        + _language_clause(language, language_level)
        + f'Set the top-level "difficulty" field to "{difficulty}" and tune health, check DCs, '
          f"fail_damage and monsters to the {difficulty} preset in the spec.\n"
        + "Write a 'prologue' (3-6 sentences of pre-history: who the player is, the world, the "
          "inciting incident, and the stakes). Design a COHERENT, connected map — regions that "
          "link logically, no random teleports, no set of rooms the player can circle at zero "
          "cost, and most choices moving the story FORWARD. Every location must be reachable and "
          "able to reach an ending; no dead items; no zero-cost infinite-retry checks; give every "
          "monster a flee or alternate route.\n"
        + "BRANCHING: most non-ending locations need 2-3 meaningful choices; never chain more "
          "than 2-3 single-choice locations in a row (a corridor fails the coherence gate).\n"
        + "ITEMS: every item must be introduced in the narrative — mention the object in the "
          "granting location's description or grant it via an explicit pick-up choice "
          "(gives_item). Items must never appear out of nowhere, and the same item must not be "
          "collectable twice on one path."
    )
    return system, user


def generate_story_api(theme, difficulty, length, title_hint, api_key, provider, model,
                       language="English", language_level="C2"):
    """Author a story via the chosen provider; validate + repair (correctness only) up to 3 times.
    Returns (story_or_None, problems_list) — problems empty == passes correctness.
    (The CLI agent in story_agent.py wraps this with the coherence + balance gates too.)"""
    system, user = build_prompts(theme, difficulty, length, title_hint, language, language_level)
    messages = [{"role": "user", "content": user}]
    story, problems = None, ["no output produced"]
    for _ in range(3):
        text = call_model(provider, model, system, messages, api_key)
        story, perr = extract_json(text)
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


# ── the full gated pipeline (shared by the app's Create page AND story_agent.py) ──
def gate_report(path, difficulty):
    """Run ALL three gates on a story file. Returns (all_ok, feedback_lines, summary_dict)."""
    story = load_story_file(path)
    problems = validate_story_dict(story)
    coh_ok, coh_items = coherence_check(path)
    verdict, bal_lines = balance_check(path, difficulty)
    ok = (not problems) and coh_ok and (verdict == "PASS")
    feedback = []
    if problems:
        feedback.append("CORRECTNESS — fix broken links / reachability: " + "; ".join(problems[:20]))
    if not coh_ok:
        feedback.append("COHERENCE — the map/opening needs work: " + "  ".join(coh_items[:20]))
    if verdict != "PASS":
        feedback.append(f"BALANCE — '{difficulty}' target not met ({verdict}): " + "; ".join(bal_lines[:8]))
    summary = {"correctness": not problems, "coherence": coh_ok,
               "balance": verdict, "bal_lines": bal_lines}
    return ok, feedback, summary


def create_story(theme, difficulty, length=14, title="", api_key=None, provider=None,
                 models=None, out_path=None, max_attempts=6, model_call=None, log=None,
                 keep_best=False, language="English", language_level="C2"):
    """Draft a story and iterate draft → validate → coherence → balance until EVERY gate passes,
    then save it. Returns (ok, saved_path_or_None, summary).

    On full success a clean story is saved and ok=True. If no attempt passes within the budget
    (or every model hits its free-tier limit) and `keep_best=True`, the best draft so far is
    saved with `draft: true` + a `gate_summary` so the work isn't lost — returned as
    (False, draft_path, summary-with-'draft':True). With keep_best=False, failure returns
    (False, None, summary). Free-tier-safe via the model fallback chain.

    `model_call(system, messages) -> text` is injectable for tests; by default it calls the
    provider with the fallback chain."""
    log = log or (lambda *a: None)
    provider = provider or gen_provider()
    models = models or gen_models(provider)
    if api_key is None:
        api_key = env_api_key(provider)
    system, user = build_prompts(theme, difficulty, length, title, language, language_level)
    if model_call is None:
        def model_call(system, messages):
            text, _used = call_with_fallback(provider, models, system, messages, api_key, log=log)
            return text

    def _score(s):
        return int(s["correctness"]) + int(s["coherence"]) + int(s["balance"] == "PASS")

    messages = [{"role": "user", "content": user}]
    tmp = tempfile.NamedTemporaryFile(prefix="story_engine_", suffix=".json", delete=False).name
    best = None          # (score, story_dict, summary)
    limit_error = None
    try:
        for attempt in range(1, max_attempts + 1):
            log(f"[{attempt}/{max_attempts}] drafting …")
            try:
                text = model_call(system, messages)
            except Exception as e:               # model/provider unavailable (e.g. all limits hit)
                limit_error = e
                log(f"    ! model unavailable — stopping: {str(e)[:120]}")
                break
            story, perr = extract_json(text)
            if story is None:
                log(f"    ✗ unparseable JSON ({perr})")
                messages += [{"role": "assistant", "content": text or ""},
                             {"role": "user", "content": f"{perr}. Resend ONLY the complete corrected JSON object."}]
                continue
            save_story_file(story, tmp)
            ok, feedback, summary = gate_report(tmp, difficulty)
            if best is None or _score(summary) >= best[0]:
                best = (_score(summary), story, summary)
            log(f"    validate:{'OK' if summary['correctness'] else 'FAIL'}  "
                f"coherence:{'OK' if summary['coherence'] else 'REVIEW'}  balance:{summary['balance']}")
            if ok:
                final = out_path or unique_story_path(story.get("title") or theme)
                save_story_file(story, final)
                log(f"    ✓ all gates green — saved to {final}")
                return True, final, summary
            messages += [{"role": "assistant", "content": json.dumps(story)},
                         {"role": "user", "content":
                          "Your story did NOT pass all gates. Fix EVERY item below and resend ONLY the "
                          "full corrected JSON. Keep the same theme and difficulty.\n- " + "\n- ".join(feedback)}]
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    # no attempt passed every gate
    if keep_best and best is not None:
        _, story, summary = best
        draft = dict(story)
        draft["draft"] = True
        draft["gate_summary"] = {k: summary[k] for k in ("correctness", "coherence", "balance")}
        path = out_path or unique_story_path((story.get("title") or theme) + " draft")
        save_story_file(draft, path)
        log(f"    saved best draft to {path} (did not pass all gates)")
        result = dict(summary)
        result["draft"] = True
        if limit_error:
            result["limit_error"] = str(limit_error)
        return False, path, result
    if limit_error and best is None:
        raise limit_error                         # nothing usable produced and the API was down
    return False, None, (best[2] if best else None)
