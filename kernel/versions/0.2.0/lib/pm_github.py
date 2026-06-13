"""
pm_github.py (v0.2.0) — PRODUCTION GitHub Projects v2 sync for the Zaude PM layer [L13].

Hardened per codex review:
- Typed GitHubError; API calls retry on rate-limit/5xx and RAISE on real errors (no silent
  wrong-state). Callers only mutate the map after an item fully succeeds; the map is persisted
  incrementally so a crash never duplicates issues.
- Secret hardening: the PAT is read ONLY from ~/.zaude/secrets/github-pat; the path must not be a
  symlink and must resolve under that dir, else we refuse. The token is never echoed/logged/
  persisted — only ids/urls go to .zaude/pm/github.json.
- Idempotent provision (adopt an existing Project by title; create only missing fields).
- Bidirectional: sync() pushes trace->GitHub; pull() reconciles PM-owned business edits back into
  the trace (lifecycle = trace-wins; business fields = PM-wins -> signed trace rows).
stdlib only.
"""
import os
import time
import json
import urllib.request
import urllib.error

GQL = "https://api.github.com/graphql"
REST = "https://api.github.com"
_SECRET_DIR = os.path.join(os.path.expanduser("~"), ".zaude", "secrets")
_SECRET = os.path.join(_SECRET_DIR, "github-pat")

STATUS_OPTS = [
    ("Intake", "PURPLE", "Ziad's column — drop ideas here"),
    ("Backlog", "BLUE", "Promoted, refined, ready"),
    ("Clarified", "BLUE", ""), ("Designed", "BLUE", ""), ("Approved", "BLUE", ""),
    ("In Progress", "YELLOW", ""), ("In Review", "ORANGE", ""), ("Verifying", "ORANGE", ""),
    ("Shippable", "GREEN", ""), ("Released", "GREEN", ""), ("Closed", "GRAY", ""),
]
LABELS = [
    ("type:feature", "1D76DB", "A user story / feature"), ("type:tech-task", "0E8A16", "An implementation task"),
    ("type:bug", "D73A4A", "A defect"), ("type:spike", "FBCA04", "A research spike"),
    ("type:chore", "C5DEF5", "Maintenance"), ("priority:p0", "B60205", "Critical"),
    ("priority:p1", "D93F0B", "High"), ("priority:p2", "FBCA04", "Medium"), ("priority:p3", "0E8A16", "Low"),
    ("risk:low", "C2E0C6", "Low risk"), ("risk:medium", "FEF2C0", "Medium risk"),
    ("risk:high", "F9D0C4", "High risk"), ("risk:critical", "E99695", "Critical risk"),
    ("zaude:intake", "5319E7", "In intake"), ("zaude:managed", "0052CC", "Agent-managed"),
    ("zaude:generated", "BFD4F2", "Agent-generated"),
]
STATE_TO_COLUMN = {"Backlog": "Backlog", "Clarified": "Clarified", "Designed": "Designed",
                   "Approved": "Approved", "In Progress": "In Progress", "Implemented": "In Progress",
                   "Tested": "In Review", "Reviewed": "In Review", "In Review": "In Review",
                   "Verified": "Verifying", "Verifying": "Verifying", "Shippable": "Shippable",
                   "Released": "Released", "Closed": "Closed"}


class GitHubError(Exception):
    """A real GitHub API failure (never carries the token)."""


# ---------------- secret (hardened) ----------------
def _secret_ok():
    try:
        if not os.path.isfile(_SECRET) or os.path.islink(_SECRET):
            return False
        if os.path.normcase(os.path.dirname(os.path.realpath(_SECRET))) != \
           os.path.normcase(os.path.realpath(_SECRET_DIR)):
            return False
        return True
    except Exception:
        return False


def have_token():
    return _secret_ok()


def _tok():
    if not _secret_ok():
        raise GitHubError("github secret missing or unsafe (symlink / wrong location)")
    with open(_SECRET, "r", encoding="utf-8") as f:
        t = f.read().strip()
    if not t:
        raise GitHubError("github secret is empty")
    return t


# ---------------- transport (retry + rate-limit) ----------------
def _request(method, url, headers, data, retries=5):
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode()
        except urllib.error.HTTPError as e:
            h = {k.lower(): v for k, v in (e.headers or {}).items()}
            body = e.read().decode() if e.fp else ""
            if e.code in (403, 429) and (h.get("x-ratelimit-remaining") == "0" or "retry-after" in h):
                wait = int(h.get("retry-after") or 0) or max(1, int(h.get("x-ratelimit-reset", 0)) - int(time.time()))
                time.sleep(min(max(wait, 1), 30)); last = "rate-limit"; continue
            if e.code >= 500:
                time.sleep(min(2 ** attempt, 8)); last = "5xx"; continue
            return e.code, h, body
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            time.sleep(min(2 ** attempt, 8)); last = str(e)[:60]; continue
    raise GitHubError("request failed after %d retries (%s): %s %s" % (retries, last, method, url.split("?")[0]))


def gql(query, variables=None):
    st, _h, body = _request("POST", GQL,
                            {"Authorization": "Bearer " + _tok(), "User-Agent": "zaude-pm",
                             "Content-Type": "application/json"},
                            json.dumps({"query": query, "variables": variables or {}}).encode())
    d = json.loads(body or "{}")
    if "errors" in d:
        raise GitHubError("graphql: " + str(d["errors"][0].get("message", ""))[:140])
    if st >= 400:
        raise GitHubError("graphql http %s" % st)
    return d


def rest(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    st, _h, body = _request(method, REST + path,
                            {"Authorization": "Bearer " + _tok(), "User-Agent": "zaude-pm",
                             "Accept": "application/vnd.github+json"}, data)
    return st, json.loads(body or "{}")


# ---------------- provision (idempotent) ----------------
def _single(pid, name, opts, existing):
    if name in existing:
        return existing[name]
    r = gql("mutation($p:ID!,$n:String!,$o:[ProjectV2SingleSelectFieldOptionInput!]!){"
            "createProjectV2Field(input:{projectId:$p,dataType:SINGLE_SELECT,name:$n,singleSelectOptions:$o})"
            "{projectV2Field{... on ProjectV2SingleSelectField{id options{id name}}}}}",
            {"p": pid, "n": name, "o": [{"name": x, "color": "GRAY", "description": ""} for x in opts]})
    f = r["data"]["createProjectV2Field"]["projectV2Field"]
    return f["id"], {o["name"]: o["id"] for o in f["options"]}


def provision(login, repo, title):
    """Create-or-ADOPT repo + labels + Project v2 (Intake-first Status) + fields. Idempotent."""
    owner = gql("query{viewer{id}}")["data"]["viewer"]["id"]
    st, r = rest("POST", "/user/repos", {"name": repo, "private": True, "auto_init": True,
                                         "description": "Zaude backlog (agent-managed)"})
    if st == 422:
        st, r = rest("GET", "/repos/%s/%s" % (login, repo))
    if "node_id" not in r:
        raise GitHubError("could not create/adopt repo %s/%s (http %s)" % (login, repo, st))
    repo_node = r["node_id"]
    for name, color, desc in LABELS:
        s, _ = rest("POST", "/repos/%s/%s/labels" % (login, repo),
                    {"name": name, "color": color, "description": desc})
        if s == 422:  # exists -> correct any drift
            rest("PATCH", "/repos/%s/%s/labels/%s" % (login, repo, name),
                 {"color": color, "description": desc})
    # adopt an existing Project by title, else create
    found = gql("query{viewer{projectsV2(first:50){nodes{id url number title}}}}")
    proj = next((n for n in found["data"]["viewer"]["projectsV2"]["nodes"] if n["title"] == title), None)
    if proj is None:
        proj = gql("mutation($o:ID!,$t:String!){createProjectV2(input:{ownerId:$o,title:$t})"
                   "{projectV2{id url number title}}}", {"o": owner, "t": title})["data"]["createProjectV2"]["projectV2"]
    pid = proj["id"]
    gql("mutation($p:ID!,$r:ID!){linkProjectV2ToRepository(input:{projectId:$p,repositoryId:$r})"
        "{repository{name}}}", {"p": pid, "r": repo_node})
    # read existing fields
    fnodes = gql("query($p:ID!){node(id:$p){... on ProjectV2{fields(first:50){nodes{"
                 "... on ProjectV2FieldCommon{id name dataType} "
                 "... on ProjectV2SingleSelectField{id name options{id name}}}}}}}", {"p": pid})[
        "data"]["node"]["fields"]["nodes"]
    by_name = {f["name"]: f for f in fnodes if f.get("name")}
    _status_opts_in = [{"name": n, "color": c, "description": d} for n, c, d in STATUS_OPTS]
    sf = by_name.get("Status")
    if sf is None:   # default field somehow absent -> create it deterministically
        r = gql("mutation($p:ID!,$o:[ProjectV2SingleSelectFieldOptionInput!]!){createProjectV2Field("
                "input:{projectId:$p,dataType:SINGLE_SELECT,name:\"Status\",singleSelectOptions:$o})"
                "{projectV2Field{... on ProjectV2SingleSelectField{id options{id name}}}}}",
                {"p": pid, "o": _status_opts_in})
        f = r["data"]["createProjectV2Field"]["projectV2Field"]
        sf = {"id": f["id"]}; sopts = {o["name"]: o["id"] for o in f["options"]}
    else:
        sopts = {o["name"]: o["id"] for o in sf.get("options", [])}
        if "Intake" not in sopts:   # repair options so Intake is the first column
            up = gql("mutation($f:ID!,$o:[ProjectV2SingleSelectFieldOptionInput!]!){"
                     "updateProjectV2Field(input:{fieldId:$f,singleSelectOptions:$o})"
                     "{projectV2Field{... on ProjectV2SingleSelectField{id options{id name}}}}}",
                     {"f": sf["id"], "o": _status_opts_in})
            sf2 = up["data"]["updateProjectV2Field"]["projectV2Field"]
            sopts = {o["name"]: o["id"] for o in sf2["options"]}

    def adopt_single(name, opts):
        if name in by_name and by_name[name].get("options"):
            f = by_name[name]
            return f["id"], {o["name"]: o["id"] for o in f["options"]}
        return _single(pid, name, opts, {})

    type_f, type_o = adopt_single("Type", ["Feature", "Tech-Task", "Bug", "Spike", "Chore"])
    prio_f, prio_o = adopt_single("Priority", ["P0", "P1", "P2", "P3"])
    risk_f, risk_o = adopt_single("Risk", ["Low", "Medium", "High", "Critical"])
    if "work_id" in by_name:
        work_f = by_name["work_id"]["id"]
    else:
        work_f = gql("mutation($p:ID!){createProjectV2Field(input:{projectId:$p,dataType:TEXT,name:\"work_id\"})"
                     "{projectV2Field{... on ProjectV2FieldCommon{id}}}}", {"p": pid})[
            "data"]["createProjectV2Field"]["projectV2Field"]["id"]
    return {"login": login, "repo": repo, "project_id": pid, "url": proj["url"], "number": proj["number"],
            "status_field": sf["id"], "status_opt": sopts, "type_field": type_f, "type_opt": type_o,
            "prio_field": prio_f, "prio_opt": prio_o, "risk_field": risk_f, "risk_opt": risk_o,
            "work_field": work_f}


# ---------------- bodies ----------------
def _feature_body(i):
    ac = "\n".join("- [ ] %s" % a for a in i.get("acceptance_list", []))
    tasks = "\n".join("- [ ] `%s` %s" % (c, t) for c, t in i.get("children_tasks", []))
    return ("## 📖 User Story\n%s\n\n## ✅ Acceptance Criteria\n%s\n\n## 🔧 Technical Tasks\n%s\n\n"
            "## 📋 Metadata\n| field | value |\n|---|---|\n| work_id | `%s` |\n| type | Feature |\n"
            "| risk | %s |\n| priority | %s |\n| promoted from | %s |\n\n## 🎯 Definition of Done (tier-4)\n"
            "Released/Closed with **passing tests + verification** in the Zaude trace.\n\n---\n"
            "_Synced from the Zaude trace (source of truth) · `vault/%s/backlog.md`._"
            % (i.get("story", ""), ac or "_(to be detailed)_", tasks or "_(none)_", i.get("work_id", ""),
               i.get("risk", "-"), i.get("priority", "-"), i.get("intake", "-"), i.get("slug", "project")))


def _task_body(i):
    return ("## 🔧 Technical Task\n%s\n\n**Parent:** %s (`%s`)\n\n## Definition of Done\nImplemented + "
            "covered by a passing test; evidence in the Zaude trace.\n\n---\n_Generated by the Zaude agent._"
            % (i.get("title", ""), i.get("parent_title", ""), i.get("parent", "")))


def _bug_body(i):
    return ("## 🐞 Bug\n%s\n\n**Parent:** %s (`%s`)\n\n## Expected\nThe defect no longer occurs; a "
            "regression test guards it.\n\n---\n_Tracked by Zaude._"
            % (i.get("title", ""), i.get("parent_title", ""), i.get("parent", "")))


def _intake_body(i):
    return ("## 💡 Intake idea\n%s\n\n**In Ziad's intake column.** Say \"work on it\" and the agent "
            "promotes this into a Feature (user story + acceptance criteria + child tasks).\n\n"
            "| field | value |\n|---|---|\n| intake_id | `%s` |\n| status | Intake |\n\n---\n_Drop ideas here._"
            % (i.get("note", ""), i.get("id", "")))


def _opt(cfg, field, opt):
    fid = cfg.get(field + "_field")
    oid = cfg.get(field + "_opt", {}).get(opt) if opt else None
    return (fid, {"singleSelectOptionId": oid}) if oid else (None, None)


def _set_fields(pid, item, pairs):
    for fid, val in pairs:
        if fid and val is not None:
            gql("mutation($p:ID!,$i:ID!,$f:ID!,$v:ProjectV2FieldValue!){"
                "updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:$v})"
                "{projectV2Item{id}}}", {"p": pid, "i": item, "f": fid, "v": val})


def sync(cfg, board, mapping, persist=None):
    """Push the board to GitHub. Per-item: validate any existing map entry, create-or-update, set
    fields+Status, persist the map incrementally. Raises on the FIRST hard error after recording
    what succeeded (so a re-run resumes without duplicating). Returns (mapping, synced_count)."""
    login, repo, pid, so = cfg["login"], cfg["repo"], cfg["project_id"], cfg["status_opt"]

    def _persist():
        if persist:
            persist(mapping)

    def upsert(key, title, body, labels, status_name, field_pairs, close=False, fingerprint=None):
        existing = mapping.get(key)
        if existing:  # validate it still exists (404 -> recreate; other non-200 -> hard error)
            s, gi = rest("GET", "/repos/%s/%s/issues/%s" % (login, repo, existing["number"]))
            if s == 404:
                mapping.pop(key, None); _persist(); existing = None
            elif s != 200:
                raise GitHubError("validate issue #%s failed (http %s)" % (existing["number"], s))
            else:  # refresh node_id from the live issue (also heals pre-existing maps w/o 'node')
                existing["node"] = gi.get("node_id") or existing.get("node")
        if existing:
            node, number = existing["node"], existing["number"]
            s, _ = rest("PATCH", "/repos/%s/%s/issues/%s" % (login, repo, number),
                        {"title": title, "body": body, "labels": labels,
                         "state": "closed" if close else "open"})
            if s not in (200, 201):
                raise GitHubError("update issue #%s failed (http %s)" % (number, s))
        else:
            s, iss = rest("POST", "/repos/%s/%s/issues" % (login, repo),
                          {"title": title, "body": body, "labels": labels})
            if s != 201 or "node_id" not in iss:
                raise GitHubError("create issue '%s' failed (http %s)" % (title[:40], s))
            node, number = iss["node_id"], iss["number"]
            # record identity IMMEDIATELY (before add) so a crash never duplicates the issue
            mapping[key] = {"number": number, "node": node, "url": iss["html_url"], "work_id": key}
            _persist()
            if close:
                cs, _ = rest("PATCH", "/repos/%s/%s/issues/%s" % (login, repo, number), {"state": "closed"})
                if cs not in (200, 201):
                    raise GitHubError("close issue #%s failed (http %s)" % (number, cs))
        # ensure the project item (addProjectV2ItemById is idempotent — returns the existing item)
        a = gql("mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c})"
                "{item{id}}}", {"p": pid, "c": node})
        item = a["data"]["addProjectV2ItemById"]["item"]["id"]
        mapping[key]["item"] = item
        if fingerprint is not None:
            mapping[key]["synced"] = fingerprint
        _persist()
        col = STATE_TO_COLUMN.get(status_name, status_name)
        pairs = list(field_pairs)
        if col in so:
            pairs.append((cfg["status_field"], {"singleSelectOptionId": so[col]}))
        _set_fields(pid, item, pairs)
        return item

    n = 0
    for it in board.get("intake", []):
        upsert(it["id"], it["title"] or it["id"], _intake_body(it), ["zaude:intake"],
               "Intake", [(cfg["work_field"], {"text": it["id"]})]); n += 1
    for iid, meta in board.get("_all_intakes", {}).items():
        if meta.get("promoted") and iid in mapping:
            upsert(iid, meta.get("title") or iid, "_Promoted into a Feature by Zaude._",
                   ["zaude:managed"], "Backlog", [], close=True)
    items = board.get("items", {})
    feat = {w: i for w, i in items.items() if i["type"] == "feature"}
    ftitle = {w: i.get("title") for w, i in feat.items()}
    for wid, i in items.items():
        if i["type"] == "feature":
            pr, rk = i.get("priority", "P2"), i.get("risk", "Medium")
            labels = ["type:feature", "zaude:managed", "priority:%s" % pr.lower(), "risk:%s" % rk.lower()]
            pairs = [p for p in [(cfg["work_field"], {"text": wid}), _opt(cfg, "type", "Feature"),
                                 _opt(cfg, "prio", pr), _opt(cfg, "risk", rk)] if p[0]]
            upsert(wid, i["title"], _feature_body(i), labels, i.get("status", "Backlog"), pairs,
                   fingerprint={"priority": pr, "risk": rk})
        else:
            parent = feat.get(i.get("parent"))
            i2 = dict(i, parent_title=ftitle.get(i.get("parent"), ""))
            cstat = parent["status"] if parent and parent.get("status") in ("Released", "Closed") else i.get("status", "Backlog")
            if i["type"] == "bug":
                labels = ["type:bug", "zaude:managed", "priority:p2"]
                pairs = [p for p in [(cfg["work_field"], {"text": wid}), _opt(cfg, "type", "Bug"), _opt(cfg, "prio", "P2")] if p[0]]
                upsert(wid, i2["title"], _bug_body(i2), labels, cstat, pairs)
            else:
                labels = ["type:tech-task", "zaude:generated"]
                pairs = [p for p in [(cfg["work_field"], {"text": wid}), _opt(cfg, "type", "Tech-Task")] if p[0]]
                upsert(wid, i2["title"], _task_body(i2), labels, cstat, pairs)
        n += 1
    _persist()
    return mapping, n


# ---------------- pull (GitHub -> trace reconcile) ----------------
def pull(cfg, board, mapping):
    """Read PM-owned business fields (Priority/Risk) from GitHub (paginated) and reconcile against
    the trace, using the per-item fingerprint recorded at last sync to tell WHO changed what:
      - PM changed it on GitHub (remote != last-synced)         -> import (PM-wins)
      - both changed since last sync (remote != trace != synced) -> CONFLICT (don't auto-overwrite)
      - only the trace changed                                   -> nothing (next sync pushes it)
    Lifecycle Status stays trace-owned. Returns reconcile actions for the caller to record as
    signed trace rows. [L13 conflict model]"""
    pid = cfg["project_id"]
    remote, cursor = {}, None
    while True:
        d = gql("query($p:ID!,$a:String){node(id:$p){... on ProjectV2{items(first:100,after:$a){"
                "pageInfo{hasNextPage endCursor} nodes{fieldValues(first:20){nodes{"
                "... on ProjectV2ItemFieldSingleSelectValue{name field{... on ProjectV2FieldCommon{name}}} "
                "... on ProjectV2ItemFieldTextValue{text field{... on ProjectV2FieldCommon{name}}}}}}}}}}",
                {"p": pid, "a": cursor})["data"]["node"]["items"]
        for it in d["nodes"]:
            fv = {}
            for v in it["fieldValues"]["nodes"]:
                if v and v.get("field"):
                    fv[v["field"]["name"]] = v.get("name") or v.get("text")
            if fv.get("work_id"):
                remote[fv["work_id"]] = fv
        if not d["pageInfo"]["hasNextPage"]:
            break
        cursor = d["pageInfo"]["endCursor"]

    actions = []
    for wid, i in board.get("items", {}).items():
        if i["type"] != "feature" or wid not in remote:
            continue
        synced = (mapping.get(wid) or {}).get("synced", {})
        for field, ghname in (("priority", "Priority"), ("risk", "Risk")):
            r = remote[wid].get(ghname)
            tracev = i.get(field)
            last = synced.get(field)
            if r is None:
                continue
            changed_remote = (r != last) if last is not None else (r != tracev)
            changed_trace = (tracev != last) if last is not None else False
            if changed_remote and changed_trace and r != tracev:
                actions.append({"work_id": wid, "field": field, "from": tracev, "to": r, "conflict": True})
            elif changed_remote and r != tracev:
                actions.append({"work_id": wid, "field": field, "from": tracev, "to": r})
    return actions
