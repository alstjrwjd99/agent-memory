"""Memory Health: 무엇을 알고/경험했고/믿고/배웠는지 한눈에. memory-lens mod가 JSON을 읽는다."""
from __future__ import annotations

import json
from collections import Counter

from . import confidence, promote, reflect, review
from .store import KINDS, Store, today


def compute(store: Store) -> dict:
    t = today()
    items = store.items()
    active = [i for i in items if i.meta.get("status") == "active"]
    changes = []
    for i in items:
        h = i.meta.get("history") or []
        if i.kind in ("opinion", "procedure") and h:
            prev = h[-2]["confidence"] if len(h) >= 2 else None
            label = i.meta.get("statement") or i.meta.get("trigger") or i.id
            changes.append({"id": i.id, "label": str(label)[:28], "from": prev, "to": h[-1]["confidence"], "at": h[-1]["at"]})
    changes.sort(key=lambda c: c["at"], reverse=True)
    return {
        "machine": store.machine,
        "counts": {k: sum(1 for i in active if i.kind == k) for k in KINDS},
        "status": dict(Counter(str(i.meta.get("status")) for i in items)),
        "new_today": sum(1 for i in items if str(i.meta.get("created_at", "")).startswith(t)),
        "updated_today": sum(1 for i in items if str(i.meta.get("updated_at", "")).startswith(t) and not str(i.meta.get("created_at", "")).startswith(t)),
        "conflicts": [i.id for i in active if i.kind in ("opinion", "procedure") and confidence.is_conflicted(i.meta)],
        "pending_sessions": len(promote.pending(store)),
        "fresh_episodes": len(reflect.fresh_episodes(store)),
        "pending_proposals": sum(sum(1 for it in p["items"] if it["status"] == "pending") for p in review.proposals(store)),
        "recent_changes": changes[:5],
        "heuristics": {
            "active": sum(1 for i in items if i.kind == "heuristic" and i.meta.get("status") == "active"),
            "candidates": [
                {"id": i.id, "statement": str(i.meta.get("statement", ""))[:160], "evidence": len(i.meta.get("evidence") or []),
                 "level": i.meta.get("level"), "parent": i.meta.get("parent")}
                for i in items if i.kind == "heuristic" and i.meta.get("status") == "candidate"
            ],
        },
    }


def write(store: Store) -> dict:
    data = compute(store)
    store.state_dir.mkdir(parents=True, exist_ok=True)
    (store.state_dir / f"health-{store.machine}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return data


def render(h: dict) -> str:
    c = h["counts"]
    out = [
        "Memory Health",
        "",
        f"World        {c['world']:>4}",
        f"Experience   {c['experience']:>4}",
        f"Observation  {c['observation']:>4}",
        f"Opinion      {c['opinion']:>4}",
        f"Procedure    {c['procedure']:>4}",
        "",
        f"New today      {h['new_today']}",
        f"Updated today  {h['updated_today']}",
        f"Conflicts      {len(h['conflicts'])}",
        f"대기: 미처리 세션 {h['pending_sessions']} · reflect 전 episode {h['fresh_episodes']} · 승인 대기 제안 {h['pending_proposals']}",
    ]
    if h["recent_changes"]:
        out += ["", "Recent Reflection", "───────────────"]
        for ch in h["recent_changes"]:
            if ch["from"] is None:
                out.append(f"NEW {ch['label']:<28} {ch['to']:.2f}")
            else:
                arrow = "↑" if ch["to"] > ch["from"] else "↓" if ch["to"] < ch["from"] else "="
                out.append(f"{arrow}  {ch['label']:<28} {ch['from']:.2f} → {ch['to']:.2f}")
    return "\n".join(out)
