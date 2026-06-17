"""
persona.py (v0.2.0) — the OPERATOR-LEARNING layer [architecture program, Claude+codex, 2026-06-17].

Goal (operator): "record my decisions across products, then when you work autonomously, decide the
way I would." That is the 2026-standard agent-memory model (CoALA): the signed TRACE is episodic
memory; this module distills the SEMANTIC (preferences) + PROCEDURAL (rules) layers into a compact
PERSONA loaded FIRST in autonomous mode so "what would the operator do here" comes from recorded
data, not a guess.

The hard part is not write+read — it is MANAGE (research 2026): an agent that remembers everything
remembers nothing useful. This engine is deterministic about management and HARDENED (codex review):
  - SIGNALS: cheap append-only observations (the DRIVER records them; the KERNEL owns policy). The
    signal log is BOUNDED (byte-budgeted; the most-recent signals are kept) so it can't grow without
    bound, without ever loading a pathological file fully.
  - PROMOTION is tiered: a belief is TENTATIVE until reinforced PROMOTE_MIN times; only CONFIRMED
    beliefs enter the always-loaded brief. Repetition is how a real preference proves itself.
  - BOUNDED: beliefs are capped per category; stale TENTATIVE beliefs are evicted; reinforced
    beliefs are kept. No unbounded growth.
  - DECAY: confidence = reinforcement-strength (grows, never saturates) x recency (Ebbinghaus-ish,
    floored so a reinforced belief never silently vanishes). Reinforcement refreshes recency.
  - DRIFT: a new statement that is SIMILAR-BUT-NOT-A-MATCH to a confirmed same-category belief is
    flagged as a possible drift / similarity conflict (a cheap token heuristic — surfaced for the
    operator to resolve, NOT asserted as semantic contradiction).
  - ROBUST: a corrupted / schema-drifted profile is sanitized on load and never raises.
  - PRIVATE: operator-private under .zaude/persona/ (gitignored, 0700/0600, never pushed); every
    stored string is secret-REDACTED in the kernel — privacy is enforced, not policy-by-comment.

Truly leaf (stdlib only; its own atomic write — no trace/state import). Never raises.
"""
import os
import re
import json
import time

CATEGORIES = ("preference", "rule", "risk_posture")
SIGNAL_KINDS = ("correction", "acceptance", "rejection", "stated_rule", "preference")

PROMOTE_MIN = 2              # reinforcement at/above which a belief is CONFIRMED (enters the brief)
RECENCY_DAYS = 120.0        # recency horizon for the decay factor (preferences are fairly stable)
RECENCY_FLOOR = 0.30        # a reinforced belief keeps at least this much recency weight
MAX_PER_CATEGORY = 40       # hard cap on beliefs per category (evict tentative/stale first)
TENTATIVE_TTL_DAYS = 45.0   # an un-reinforced tentative belief older than this is evictable
MAX_SIGNALS = 2000          # target retained signals (log is byte-bounded to ~the most-recent N)
MAX_PROVENANCE = 5          # cap on per-belief provenance sources (newest-unique kept)
_SIG_TAIL_BYTES = MAX_SIGNALS * 800   # bounded tail read when capping a huge signal log
_MATCH = 0.60               # token-similarity at/above which two statements are the "same" belief
_DRIFT_LO = 0.35            # similar-but-not-a-match band -> possible drift vs a confirmed belief
_DAY = 86400.0

# stripped before matching so short restatements reinforce ("use pytest" == "always use pytest")
_STOP = {"a", "an", "the", "i", "we", "to", "of", "and", "or", "is", "be", "always", "never",
         "please", "just", "prefer", "prefers", "preferred", "like", "likes", "want", "wants",
         "should", "must", "my", "me", "you", "it", "this", "that"}

# secret-shaped tokens redacted before anything is persisted (privacy enforced in the kernel)
_SECRET_RES = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), re.compile(r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-.]+"),
    re.compile(r"\bx-access-token:[^\s@]+", re.I), re.compile(r"://[^/@\s]+:[^/@\s]+@"),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"), re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
]


def _redact(t):
    s = (t or "")
    try:
        for rx in _SECRET_RES:
            s = rx.sub("<redacted>", s)
    except Exception:
        return ""
    return s


def _dir(zd):
    return os.path.join(zd, "persona")


def _profile_path(zd):
    return os.path.join(_dir(zd), "profile.json")


def _signals_path(zd):
    return os.path.join(_dir(zd), "signals.jsonl")


def _ensure_dir(zd):
    d = _dir(zd)
    os.makedirs(d, exist_ok=True)
    try:
        os.chmod(d, 0o700)            # operator-private (best-effort; Windows ignores)
    except Exception:
        pass
    return d


def _write_atomic(path, obj):
    """Own atomic write (leaf lib — no trace import). tmp + os.replace; 0600. Never raises."""
    try:
        tmp = path + ".tmp.%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, separators=(",", ":"))
        try:
            os.chmod(tmp, 0o600)
        except Exception:
            pass
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def _norm(t):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (t or "").lower())).strip()


def _tokens(t):
    return {w for w in _norm(t).split() if w not in _STOP}


def _sim(a, b):
    """Similarity in [0,1]: 1.0 if one token-set contains the other (handles short restatements),
    else Jaccard. Empty-after-stopwords sets fall back to raw-token Jaccard."""
    sa, sb = _tokens(a), _tokens(b)
    if not sa or not sb:
        sa, sb = set(_norm(a).split()), set(_norm(b).split())
    if not sa or not sb:
        return 0.0
    if sa <= sb or sb <= sa:
        return 1.0
    return len(sa & sb) / float(len(sa | sb))


def _clean_belief(b, idx):
    """Coerce one raw entry to a well-formed belief, or None. Defends brief()/beliefs() against a
    corrupted-but-valid-JSON profile (codex-CRITICAL)."""
    if not isinstance(b, dict):
        return None
    stmt = b.get("statement")
    if not isinstance(stmt, str) or not stmt.strip():
        return None
    stmt = _redact(stmt).strip()[:300]            # redact LOADED data too — an old/corrupt
    if not stmt:                                  # profile may hold a token (codex-HIGH)
        return None
    cat = b.get("category")
    cat = cat if cat in CATEGORIES else "preference"
    try:
        reinf = max(1, int(b.get("reinforcement", 1)))
    except Exception:
        reinf = 1
    def _f(v, d):
        try:
            return float(v)
        except Exception:
            return d
    now = time.time()
    prov = b.get("provenance")
    if isinstance(prov, list):
        prov = [_redact(p)[:80] for p in prov if isinstance(p, str) and p][:MAX_PROVENANCE]
    else:
        prov = []
    bid = b.get("id")
    if not (isinstance(bid, str) and re.match(r"^B\d+$", bid)):   # only generated ids; an arbitrary
        bid = "B%d" % idx                                         # 'id' could carry a secret (codex)
    return {"id": bid, "category": cat, "statement": stmt[:300], "provenance": prov,
            "reinforcement": reinf, "first_seen": _f(b.get("first_seen"), now),
            "last_seen": _f(b.get("last_seen"), now)}


def _load(zd):
    """Read + SANITIZE the profile. Returns {schema, next_id, beliefs:[clean...]}. Never raises."""
    raw = None
    try:
        with open(_profile_path(zd), "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        raw = None
    beliefs, next_id = [], 1
    if isinstance(raw, dict):
        raw_beliefs = raw.get("beliefs")
        if not isinstance(raw_beliefs, list):      # {"beliefs": 1/true/...} must not crash (codex)
            raw_beliefs = []
        for i, b in enumerate(raw_beliefs, start=1):
            cb = _clean_belief(b, i)
            if cb:
                beliefs.append(cb)
        try:
            next_id = max(1, int(raw.get("next_id", 1)))
        except Exception:
            next_id = 1
    # next_id must exceed any existing Bn so ids are never reused after forget() (codex-MEDIUM)
    for b in beliefs:
        m = re.match(r"B(\d+)$", b["id"])
        if m:
            next_id = max(next_id, int(m.group(1)) + 1)
    profile = {"schema": 1, "next_id": next_id, "beliefs": beliefs}
    _evict(profile)        # COUNT-cap only (no time): bounds a huge/corrupt profile on READ without
    return profile         #   time-deleting recent beliefs (codex-HIGH)


def _save(zd, profile):
    _ensure_dir(zd)
    return _write_atomic(_profile_path(zd), profile)


def _evict(profile, now=None):
    """Bound growth. The per-category COUNT cap is ALWAYS enforced (so a huge/corrupt profile is
    bounded even on read). Time-based stale-tentative eviction runs ONLY when a `now` is given —
    i.e. on WRITE (promote), with the write's clock. It must NOT run on every read with real-now,
    or a recent-but-historically-timestamped tentative belief would be deleted before it can be
    reinforced (replayed history / tests). [codex: bound reads without time-deleting]"""
    bs = profile["beliefs"]
    if now is not None:
        bs = [b for b in bs if b["reinforcement"] >= PROMOTE_MIN
              or (now - b["last_seen"]) <= TENTATIVE_TTL_DAYS * _DAY]
    # 2. per-category cap
    out, by_cat = [], {}
    for b in bs:
        by_cat.setdefault(b["category"], []).append(b)
    for cat, items in by_cat.items():
        if len(items) > MAX_PER_CATEGORY:
            # keep the strongest: sort by (confirmed, reinforcement, recency) desc, keep top N
            items.sort(key=lambda b: (b["reinforcement"] >= PROMOTE_MIN, b["reinforcement"],
                                      b["last_seen"]), reverse=True)
            items = items[:MAX_PER_CATEGORY]
        out.extend(items)
    profile["beliefs"] = out


def observe(zd, kind, text, source=None, now=None):
    """Append a cheap, REDACTED preference signal. The log is capped (most-recent MAX_SIGNALS).
    Never raises."""
    now = now if now is not None else time.time()
    row = {"kind": kind if kind in SIGNAL_KINDS else "preference",
           "text": _redact(text)[:500], "source": _redact(source)[:80] if source else None, "ts": now}
    try:
        _ensure_dir(zd)
        sp = _signals_path(zd)
        with open(sp, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
        try:
            os.chmod(sp, 0o600)
        except Exception:
            pass
        # cap WITHOUT loading a pathological file: only when the byte size exceeds the tail budget,
        # read just the last _SIG_TAIL_BYTES and keep the last MAX_SIGNALS whole lines (codex-MEDIUM).
        try:
            if os.path.getsize(sp) > _SIG_TAIL_BYTES:
                with open(sp, "rb") as f:
                    f.seek(-_SIG_TAIL_BYTES, os.SEEK_END)
                    tail = f.read().decode("utf-8", "ignore")
                lines = [ln for ln in tail.split("\n")[1:] if ln][-MAX_SIGNALS:]   # drop partial 1st
                with open(sp, "w", encoding="utf-8") as f:
                    f.write(("\n".join(lines) + "\n") if lines else "")
                try:
                    os.chmod(sp, 0o600)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass
    return row


def promote(zd, category, statement, source=None, weight=1, now=None):
    """Upsert a belief (redacted). Near-match in the same category -> REINFORCE (+weight, refresh
    recency); else add TENTATIVE. Returns the belief with .drift + .conflicts when it is similar to
    (but not a match for) a CONFIRMED same-category belief. Bounded + never raises."""
    now = now if now is not None else time.time()
    cat = category if category in CATEGORIES else "preference"
    stmt = _redact(statement).strip()[:300]
    if not stmt:
        return {"error": "empty statement", "id": None, "drift": False, "conflicts": []}
    try:
        prof = _load(zd)
        beliefs = prof["beliefs"]
        for b in beliefs:
            if b["category"] == cat and _sim(b["statement"], stmt) >= _MATCH:
                b["reinforcement"] += max(1, int(weight))
                b["last_seen"] = now
                if source:
                    rs = _redact(source)[:80]
                    if rs and rs not in b["provenance"]:
                        b["provenance"].append(rs)
                    b["provenance"] = b["provenance"][-MAX_PROVENANCE:]   # cap (codex-HIGH)
                _evict(prof, now)
                _save(zd, prof)
                return dict(b, drift=False, conflicts=[])
        conflicts = [b["statement"] for b in beliefs
                     if b["category"] == cat and b["reinforcement"] >= PROMOTE_MIN
                     and _DRIFT_LO <= _sim(b["statement"], stmt) < _MATCH]
        bid = "B%d" % prof["next_id"]
        prof["next_id"] += 1
        belief = {"id": bid, "category": cat, "statement": stmt,
                  "provenance": [_redact(source)[:80]] if source else [],
                  "reinforcement": max(1, int(weight)), "first_seen": now, "last_seen": now}
        beliefs.append(belief)
        _evict(prof, now)
        _save(zd, prof)
        return dict(belief, drift=bool(conflicts), conflicts=conflicts)
    except Exception as e:
        return {"error": str(e)[:80], "id": None, "drift": False, "conflicts": []}


def forget(zd, belief_id):
    try:
        prof = _load(zd)
        n0 = len(prof["beliefs"])
        prof["beliefs"] = [b for b in prof["beliefs"] if b["id"] != belief_id]
        if len(prof["beliefs"]) != n0:
            _save(zd, prof)            # next_id is preserved by _load, so ids never repeat
            return True
    except Exception:
        pass
    return False


def _confidence(b, now):
    """confidence = strength x recency. strength = reinforcement/(reinforcement+1) GROWS and never
    saturates (x2->0.67, x5->0.83, x20->0.95). recency decays, floored so a reinforced belief never
    vanishes."""
    reinf = b["reinforcement"]
    strength = reinf / float(reinf + 1)
    days = max(0.0, (now - b["last_seen"]) / _DAY)
    recency = max(RECENCY_FLOOR, 1.0 - days / RECENCY_DAYS)
    return round(strength * recency, 2)


def beliefs(zd, confirmed_only=False, now=None):
    """All beliefs, MOST-REINFORCED FIRST (then confidence). Each carries live confidence+confirmed.
    Never raises."""
    now = now if now is not None else time.time()
    out = []
    for b in _load(zd)["beliefs"]:
        confirmed = b["reinforcement"] >= PROMOTE_MIN
        if confirmed_only and not confirmed:
            continue
        out.append(dict(b, confidence=_confidence(b, now), confirmed=confirmed))
    out.sort(key=lambda x: (not x["confirmed"], -x["reinforcement"], -x["confidence"]))
    return out


def brief(zd, max_items=12, now=None):
    """The compact 'decide as the operator would' block — CONFIRMED beliefs only, grouped by
    category, most-reinforced first. Empty string while the persona is still learning. Never raises."""
    now = now if now is not None else time.time()
    conf = beliefs(zd, confirmed_only=True, now=now)[:max_items]
    if not conf:
        return ""
    by_cat = {}
    for b in conf:
        by_cat.setdefault(b["category"], []).append(b)
    lines = ["# Operator persona (decide as the operator would; confirmed from recorded decisions)"]
    for cat, label in (("risk_posture", "Risk posture"), ("rule", "Rules"), ("preference", "Preferences")):
        items = by_cat.get(cat) or []
        if items:
            lines.append("\n**%s:**" % label)
            for b in items:
                lines.append("- %s  _(x%d, conf %.2f)_" % (b["statement"], b["reinforcement"], b["confidence"]))
    return "\n".join(lines)


def render_md(zd, now=None):
    """Write the brief to .zaude/persona/persona.md (operator-private). Returns the path or None."""
    try:
        _ensure_dir(zd)
        txt = brief(zd, now=now)
        p = os.path.join(_dir(zd), "persona.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(txt + ("\n" if txt else "_(persona still learning — no confirmed beliefs yet)_\n"))
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass
        return p
    except Exception:
        return None
