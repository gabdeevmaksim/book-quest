"""sounds.py — small sound effects for the app: button clicks, the dice roll, a new item.

The clips are assets/sounds/*.mp3 (made by scripts/make_sounds.py). They are handed to the
browser once per run as data URIs and played there with JavaScript:

* click — entirely client-side: one listener on the page plays it for every <button> press,
  so there is no server round-trip and no per-button code.
* roll / item / success / fail — the app asks for them: `play_now("roll")` (sent at once, used by
  animate_roll) and `play("item")`, `play("success")`, `play("fail")` (queued; `flush()` sends the
  queue at the end of a run, so a sound asked for just before `st.rerun()` still plays on the
  next run — the outcome sound therefore arrives with the outcome card, after the roll).

Browsers only allow sound after the visitor has interacted with the page — every effect here
follows a click, so that is always the case. The player's on/off choice lives in
`fbmeta_sound_on` (the `fbmeta_` prefix survives app.clear_session). `QUEST_SOUND=0` turns the
feature off for everyone and hides the switch.
"""
import base64
import json
import os
import uuid
from functools import lru_cache

import streamlit as st

SOUND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sounds")
NAMES = ("click", "roll", "item", "success", "fail")
VOLUME = {"click": 0.45, "roll": 0.8, "item": 0.7, "success": 0.7, "fail": 0.8}
PREF_KEY = "fbmeta_sound_on"        # the player's choice (kept across screens)
QUEUE_KEY = "fbmeta_sound_queue"    # sounds asked for but not yet sent to the browser


def available():
    """The feature is switched on for this server and the clips are there."""
    return os.environ.get("QUEST_SOUND", "1") != "0" and bool(_sources())


def enabled():
    return available() and bool(st.session_state.get(PREF_KEY, True))


@lru_cache(maxsize=1)
def _sources():
    out = {}
    for name in NAMES:
        try:
            with open(os.path.join(SOUND_DIR, f"{name}.mp3"), "rb") as f:
                out[name] = "data:audio/mpeg;base64," + base64.b64encode(f.read()).decode("ascii")
        except OSError:
            pass
    return out


_HIDE = ("<style>div[data-testid='stElementContainer']:has(.qb-sfx),"
         ".element-container:has(.qb-sfx){display:none!important}</style>")

_INIT_JS = """<span class="qb-sfx"></span><script>
(function(){
  var P = window.parent || window;
  var S = P.__qbSfx = P.__qbSfx || {played: {}};
  S.on = __ON__; S.src = __SRC__; S.vol = __VOL__;
  S.play = function(n){
    if (!S.on || !S.src[n]) return;
    try { var a = new P.Audio(S.src[n]); a.volume = S.vol[n] || 0.7;
          var p = a.play(); if (p && p.catch) p.catch(function(){}); } catch (e) {}
  };
  if (!S.bound) {
    S.bound = true;
    P.document.addEventListener('click', function(e){
      var b = e.target && e.target.closest ? e.target.closest('button') : null;
      if (b && !b.disabled) P.__qbSfx.play('click');
    }, true);
  }
})();
</script>"""

_PLAY_JS = """<span class="qb-sfx"></span><script>
(function(){
  var P = window.parent || window, id = "__ID__", names = __NAMES__, tries = 0;
  function go(){
    var S = P.__qbSfx;
    if (!S || !S.play) { if (tries++ < 30) setTimeout(go, 100); return; }
    if (S.played[id]) return;
    S.played[id] = 1;
    names.forEach(function(n, i){ setTimeout(function(){ S.play(n); }, i * 450); });
  }
  go();
})();
</script>"""


def init_html(on):
    return (_INIT_JS.replace("__ON__", "true" if on else "false")
            .replace("__SRC__", json.dumps(_sources() if on else {}))
            .replace("__VOL__", json.dumps(VOLUME)))


def play_html(names, nonce=None):
    return (_PLAY_JS.replace("__ID__", nonce or uuid.uuid4().hex)
            .replace("__NAMES__", json.dumps(list(names))))


def _inject(html):
    """Run a script in the page. st.html executes JavaScript only when asked to (newer Streamlit);
    older releases fall back to a zero-height component iframe, where window.parent is the app."""
    try:
        st.html(html, unsafe_allow_javascript=True)
    except TypeError:
        import streamlit.components.v1 as components
        components.html(html, height=0)


def init():
    """Call once at the top of every run: installs the player + the button-click listener."""
    if not available():
        return
    st.html(_HIDE)
    _inject(init_html(enabled()))


def play(name):
    """Queue a sound for the end of this run (or of the next one, if this run is cut short by st.rerun)."""
    if enabled() and name in NAMES:
        q = st.session_state.setdefault(QUEUE_KEY, [])
        if name not in q:
            q.append(name)


def play_now(name):
    """Send a sound to the browser immediately — for moments in the middle of a run (the dice)."""
    if enabled() and name in NAMES:
        _inject(play_html([name]))


def flush():
    """Call at the very end of a run: plays whatever was queued."""
    q = st.session_state.pop(QUEUE_KEY, None)
    if q and enabled():
        _inject(play_html(q))


def toggle(where):
    """The on/off switch (one per screen that shows it; `where` keeps the widget keys apart)."""
    if not available():
        return
    key = f"sound_toggle_{where}"

    def _set():
        st.session_state[PREF_KEY] = bool(st.session_state[key])

    st.toggle("🔊 Sound effects", value=bool(st.session_state.get(PREF_KEY, True)), key=key, on_change=_set)
