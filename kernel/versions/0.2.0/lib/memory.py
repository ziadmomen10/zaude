"""
memory.py (v0.2.0) — COLLECTIVE MEMORY [operator-learning layer, Claude+codex, 2026-06-17].

The retrieval layer of the operator-learning layer: a durable, searchable store of facts, lessons,
and decisions ("learn about me + lessons learned"). The persona (persona.py) distills the SEMANTIC
preference profile; this module is the broader recall store the driver writes lessons to and reads
back from. The signed trace stays the episodic source of truth; this is derived, retrievable
context — never authoritative.

Engineered with the SAME hardening persona earned through 4 codex rounds (baked in from the start):
  - REDACT every persisted string (write AND load) — privacy enforced in the kernel, not by comment.
  - BOUNDED: append-only log capped to the most-recent entries (byte-budgeted; never loads a
    pathological file fully).
  - ROBUST: a corrupted / schema-drifted line is skipped, never raises.
  - PRIVATE: operator-private under .zaude/memory/ (gitignored, 0700/0600, never pushed).
  - DETERMINISTIC recall: a stdlib TF-IDF-lite scorer (zero deps — keeps the kernel dependency-free);
    no external vector DB in v1 (Mem0/Zep/Letta are the graduation path if it earns it).

Leaf lib (stdlib only; own atomic-ish writes — no trace/state import). Never raises.
"""
import os
import re
import json
import math
import time

MAX_ENTRIES = 5000          # target retained entries (byte-bounded to ~the most-recent this many)
_TAIL_BYTES = MAX_ENTRIES * 400
_DAY = 86400.0

_STOP = {"a", "an", "the", "is", "are", "to", "of", "and", "or", "in", "on", "for", "with", "it",
         "this", "that", "be", "as", "at", "by", "we", "i", "you", "do", "not", "no", "so"}

_SECRET_RES = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), re.compile(r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-.]+"),
    re.compile(r"\bx-access-token:[^\s@]+", re.I), re.compile(r"://[^/@\s]+:[^/@\s]+@"),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"), re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
]


def _redact(t):
    s = t or ""
    try:
        for rx in _SECRET_RES:
            s = rx.sub("<redacted>", s)
    except Exception:
        return ""
    return s


def _dir(zd):
    return os.path.join(zd, "memory")


def _path(zd):
    return os.path.join(_dir(zd), "entries.jsonl")


def _ensure_dir(zd):
    d = _dir(zd)
    os.makedirs(d, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except Exception:
        pass
    return d


def _tokens(t):
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", (t or "").lower()).split() if w not in _STOP]


def remember(zd, text, tags=None, source=None, now=None):
    """Append a REDACTED memory entry. Bounded (byte-budgeted tail kept). Never raises."""
    now = now if now is not None else time.time()
    # cap raw input BEFORE running the redaction regexes (don't regex a multi-MB pasted blob), then
    # redact over that bounded window, then cap to the stored length (codex). The tag loop STOPS at
    # 10 so a huge/generator `tags` can't do unbounded work (codex).
    clean_tags = []
    seen = 0
    if not isinstance(tags, (list, tuple)):   # a non-iterable `tags` must not raise (never-raises)
        tags = []
    for t in tags:
        seen += 1
        if seen > 100:               # TOTAL-iteration bound (not just accepted): a giant list of
            break                    # non-strings / an infinite generator can't loop forever (codex)
        if isinstance(t, str):
            clean_tags.append(_redact(t[:160])[:40])
            if len(clean_tags) >= 10:
                break
    row = {"text": _redact((text or "")[:4000])[:1000], "tags": clean_tags,
           "source": (_redact((source or "")[:160])[:80] or None) if source else None, "ts": now}
    if not row["text"].strip():
        return row
    try:
        _ensure_dir(zd)
        p = _path(zd)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass
        # bounded cap WITHOUT loading a pathological file: tail-read only when oversized
        try:
            if os.path.getsize(p) > _TAIL_BYTES:
                with open(p, "rb") as f:
                    f.seek(-_TAIL_BYTES, os.SEEK_END)
                    tail = f.read().decode("utf-8", "ignore")
                lines = [ln for ln in tail.split("\n")[1:] if ln][-MAX_ENTRIES:]
                with open(p, "w", encoding="utf-8") as f:
                    f.write(("\n".join(lines) + "\n") if lines else "")
                try:
                    os.chmod(p, 0o600)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass
    return row


def _load(zd):
    """Read + SANITIZE entries (redact loaded text/tags/source; skip corrupt lines). The READ ITSELF
    is byte-bounded — a pathological/corrupt file is never loaded fully (codex-HIGH): when oversized,
    seek and read only the last _TAIL_BYTES and drop the partial first line. Never raises."""
    out = []
    p = _path(zd)
    try:
        sz = os.path.getsize(p)
    except Exception:
        return out
    try:
        if sz > _TAIL_BYTES:
            with open(p, "rb") as f:
                f.seek(-_TAIL_BYTES, os.SEEK_END)
                data = f.read().decode("utf-8", "ignore")
            data = data.split("\n", 1)[1] if "\n" in data else ""   # drop the partial first line
        else:
            with open(p, "r", encoding="utf-8") as f:
                data = f.read()
    except Exception:
        return out
    for line in data.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if not isinstance(d, dict) or not isinstance(d.get("text"), str):
            continue
        tags = d.get("tags")
        tags = [_redact(t)[:40] for t in tags if isinstance(t, str)][:10] if isinstance(tags, list) else []
        try:
            ts = float(d.get("ts", 0.0))
        except Exception:
            ts = 0.0
        out.append({"text": _redact(d["text"])[:1000], "tags": tags,
                    "source": _redact(d.get("source"))[:80] if isinstance(d.get("source"), str) else None,
                    "ts": ts})
        if len(out) > MAX_ENTRIES * 2:        # hard read bound even if the file is pathological
            break
    return out[-MAX_ENTRIES:]


def recall(zd, query, k=5):
    """Return the top-k most relevant entries for `query` via a deterministic TF-IDF-lite score
    (stdlib, zero deps). Entries with score 0 are excluded. Never raises."""
    try:
        try:
            k = int(k)
        except Exception:
            k = 5
        if k <= 0:                 # honest top-k: k<=0 returns nothing (codex-LOW)
            return []
        entries = _load(zd)
        if not entries:
            return []
        q = set(_tokens(query))
        if not q:
            return []
        n = len(entries)
        df = {}
        toks = []
        for e in entries:
            et = _tokens(e["text"] + " " + " ".join(e.get("tags") or []))
            toks.append(et)
            for w in set(et):
                df[w] = df.get(w, 0) + 1
        scored = []
        for e, et in zip(entries, toks):
            if not et:
                continue
            tf = {}
            for w in et:
                tf[w] = tf.get(w, 0) + 1
            score = 0.0
            for w in q:
                if w in tf:
                    # add-1 smoothed idf: stays POSITIVE even on a tiny corpus where a term appears
                    # in every entry (df==n) — otherwise a match against the only doc scores 0.
                    idf = 1.0 + math.log((n + 1) / (1 + df.get(w, 0)))
                    score += (tf[w] / float(len(et))) * idf
            if score > 0:
                scored.append((round(score, 4), e))
        scored.sort(key=lambda x: (-x[0], -x[1]["ts"]))
        return [dict(e, score=s) for s, e in scored[:k]]
    except Exception:
        return []


def count(zd):
    try:
        return len(_load(zd))
    except Exception:
        return 0
