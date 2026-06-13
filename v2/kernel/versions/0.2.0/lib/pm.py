"""
pm.py (v0.2.0) — the Product-Management / backlog layer [L13], OFFLINE form.

The board is a PROJECTION of the same tamper-evident trace: PM events are trace rows
(pm_intake / pm_promote / pm_workitem / pm_move), so the backlog can't drift and is signed.
When a GitHub token is provided, the same events sync to a Projects v2 board; with no token it
runs against this local projection (the spec's `--offline` degrade). stdlib only.

Work-item taxonomy (GitHub has no native types -> labels): feature (=user story) / tech-task /
bug / spike / chore. The PM (Ziad) owns Intake; the agent owns promotion + lifecycle movement.
"""

INTAKE = "Intake"
BACKLOG = "Backlog"


def _title_from(note, n=8):
    words = (note or "").strip().split()
    return " ".join(words[:n]) + ("…" if len(words) > n else "")


def next_intake_id(board):
    return "ZI-%03d" % (len(board["_all_intakes"]) + 1)


def next_work_id(board, year=2026):
    return "ZA-%d-%05d" % (year, len(board["items"]) + 1)


def intake_row(intake_id, note):
    return {"kind": "pm_intake", "intake_id": intake_id,
            "title": _title_from(note), "note": note, "status": INTAKE}


def promote_rows(intake_id, work_id, title, story, acceptance, tasks, bugs, child_ids,
                 priority="P2", risk="Medium"):
    rows = [{"kind": "pm_promote", "intake_id": intake_id, "work_id": work_id,
             "type": "feature", "title": title, "story": story, "acceptance": acceptance,
             "priority": priority, "risk": risk, "status": BACKLOG}]
    for cid, t in zip(child_ids, tasks):
        rows.append({"kind": "pm_workitem", "work_id": cid, "parent": work_id,
                     "type": "tech-task", "title": t, "status": BACKLOG})
    for cid, b in zip(child_ids[len(tasks):], bugs):
        rows.append({"kind": "pm_workitem", "work_id": cid, "parent": work_id,
                     "type": "bug", "title": b, "status": BACKLOG})
    return rows


def pm_board(rows):
    intakes = {}   # id -> {title, note, promoted}
    items = {}     # work_id -> {type, title, story, parent, status}
    for r in rows:
        k = r.get("kind")
        if k == "pm_intake":
            intakes[r["intake_id"]] = {"title": r.get("title"), "note": r.get("note"),
                                       "promoted": False}
        elif k == "pm_promote":
            iid = r.get("intake_id")
            if iid in intakes:
                intakes[iid]["promoted"] = True
            items[r["work_id"]] = {"type": "feature", "title": r.get("title"),
                                   "story": r.get("story"), "acceptance": r.get("acceptance"),
                                   "priority": r.get("priority", "P2"), "risk": r.get("risk", "Medium"),
                                   "intake": iid, "parent": None, "status": r.get("status", BACKLOG)}
        elif k == "pm_workitem":
            items[r["work_id"]] = {"type": r.get("type"), "title": r.get("title"),
                                   "story": None, "parent": r.get("parent"),
                                   "status": r.get("status", BACKLOG)}
        elif k == "pm_move":
            if r.get("work_id") in items:
                items[r["work_id"]]["status"] = r.get("to")
        elif k == "pm_field_changed":   # PM edited a business field in GitHub -> imported (PM-wins)
            wid = r.get("work_id")
            if wid in items and r.get("field"):
                items[wid][r["field"]] = r.get("value")
    # enrich features with their acceptance list + child tasks (for rich GitHub issue bodies)
    for wid, i in items.items():
        if i["type"] == "feature":
            i["work_id"] = wid
            i["acceptance_list"] = [a.strip() for a in (i.get("acceptance") or "").split(";") if a.strip()]
            i["children_tasks"] = [(cw, ci["title"]) for cw, ci in items.items()
                                   if ci.get("parent") == wid and ci["type"] == "tech-task"]
    return {
        "_all_intakes": intakes,
        "intake": [dict(id=i, **{k: v for k, v in d.items() if k != "promoted"})
                   for i, d in intakes.items() if not d["promoted"]],
        "items": items,
    }
