"""제안 승인/거절. ADD / UPDATE(근거 추가) / INVALIDATE만, DELETE 없음."""
from __future__ import annotations

import json
from pathlib import Path

from . import confidence
from .store import Store, now_iso, today

LOW_CONFIDENCE = 0.4


def proposals(store: Store, status: str | None = "pending") -> list[dict]:
    d = store.root / "proposals"
    out = []
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        p = json.loads(f.read_text(encoding="utf-8"))
        if status is None or p.get("status") == status:
            out.append(p)
    return out


def _path(store: Store, pid: str) -> Path:
    p = store.root / "proposals" / f"{pid}.json"
    if not p.exists():
        raise SystemExit(f"제안 없음: {pid}")
    return p


def _history(meta: dict, by: str, note: str) -> None:
    meta.setdefault("history", []).append(
        {"at": now_iso(), "support": len(meta.get("evidence") or []), "counter": len(meta.get("counter_evidence") or []),
         "confidence": round(confidence.of(meta), 3), "by": by, "note": note}
    )


def _merge(xs: list, ys: list) -> list:
    return list(dict.fromkeys([*(xs or []), *ys]))


def apply_item(store: Store, pid: str, it: dict) -> str:
    op = it["op"]
    if op == "evidence":
        item = store.get(it["id"])
        if not item:
            return f"#{it['n']} 대상 없음 {it['id']}"
        item.meta["evidence"] = _merge(item.meta.get("evidence"), it["supports"])
        item.meta["counter_evidence"] = _merge(item.meta.get("counter_evidence"), it["contradicts"])
        _history(item.meta, pid, it["reason"])
        # active ↔ low_confidence만 자동 전환 (invalidated/superseded는 건드리지 않음)
        status = item.meta.get("status")
        conf = confidence.of(item.meta)
        if status == "active" and conf < LOW_CONFIDENCE:
            item.meta["status"] = "low_confidence"
        elif status == "low_confidence" and conf >= LOW_CONFIDENCE:
            item.meta["status"] = "active"
        store.save(item)
        return f"#{it['n']} {item.id} 근거 갱신 → conf {confidence.of(item.meta):.2f}"
    if op == "new_opinion":
        meta = {"statement": it["statement"], "evidence": it["supports"], "counter_evidence": it["contradicts"],
                "valid_from": today(), "valid_to": None, "links": [], "source_proposal": pid}
        _history(meta, pid, it["reason"])
        item = store.add("opinion", meta, it["statement"])
        return f"#{it['n']} 새 opinion {item.id} (conf {confidence.of(meta):.2f})"
    if op == "new_procedure":
        meta = {"trigger": it["trigger"], "rules": it["rules"], "evidence": it["derived_from"], "counter_evidence": [],
                "valid_from": today(), "valid_to": None, "source_proposal": pid}
        _history(meta, pid, it["reason"])
        body = f"트리거: {it['trigger']}\n\n" + "\n".join(f"{k}. {r}" for k, r in enumerate(it["rules"], 1))
        item = store.add("procedure", meta, body)
        return f"#{it['n']} 새 procedure {item.id} (Skill 후보)"
    if op == "observe":
        same = [o for o in store.items("observation") if o.meta.get("subject") == it["subject"] and o.meta.get("status") == "active"]
        if same:
            o = same[0]
            o.meta.setdefault("previous", []).append({"at": o.meta.get("updated_at"), "summary": o.body.strip()})
            o.meta["evidence"] = _merge(o.meta.get("evidence"), it["sources"])
            o.body = it["summary"]
            store.save(o)
            return f"#{it['n']} observation 갱신 {o.id} ({it['subject']})"
        o = store.add("observation", {"subject": it["subject"], "evidence": it["sources"], "valid_from": today(), "valid_to": None}, it["summary"])
        return f"#{it['n']} 새 observation {o.id} ({it['subject']})"
    if op == "revise":
        item = store.get(it["id"])
        if not item:
            return f"#{it['n']} 대상 없음 {it['id']}"
        if item.meta.get("status") not in ("active", "low_confidence"):
            return f"#{it['n']} {item.id}는 {item.meta.get('status')} 상태라 수정하지 않음"
        # 이전 문장/규칙은 versions에 보존 (git 이력과 별개로 파일만 봐도 변천을 알 수 있게)
        prev = {"at": item.meta.get("updated_at"), "statement": item.meta.get("statement"), "rules": item.meta.get("rules"), "by": pid}
        # 수정 근거는 versions에만 기록 (evidence에 넣으면 표현만 바꿔도 confidence가 오름)
        prev["revised_with"] = it["supports"]
        item.meta.setdefault("versions", []).append({k: v for k, v in prev.items() if v is not None})
        if item.kind == "opinion":
            item.meta["statement"] = it["statement"]
            item.body = it["statement"]
        else:
            item.meta["rules"] = it["rules"]
            item.body = f"트리거: {item.meta.get('trigger')}\n\n" + "\n".join(f"{k}. {r}" for k, r in enumerate(it["rules"], 1))
        _history(item.meta, pid, f"수정: {it['reason']}")
        store.save(item)
        return f"#{it['n']} {item.id} 수정 (버전 {len(item.meta['versions']) + 1})"
    if op == "invalidate":
        item = store.get(it["id"])
        if not item:
            return f"#{it['n']} 대상 없음 {it['id']}"
        item.meta["status"] = "invalidated"
        item.meta["valid_to"] = today()
        item.meta["invalidated_reason"] = it["reason"]
        store.save(item)
        return f"#{it['n']} {item.id} invalidated"
    return f"#{it['n']} 알 수 없는 op {op}"


def decide(store: Store, pid: str, accept: bool, only: set[int] | None = None) -> list[str]:
    path = _path(store, pid)
    p = json.loads(path.read_text(encoding="utf-8"))
    log = []

    def save() -> None:
        if all(it["status"] != "pending" for it in p["items"]):
            p["status"] = "done"
        p["decided_at"] = now_iso()
        path.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    for it in p["items"]:
        if it["status"] != "pending" or (only is not None and it["n"] not in only):
            continue
        if accept:
            log.append(apply_item(store, pid, it))
            it["status"] = "applied"
        else:
            it["status"] = "rejected"
            log.append(f"#{it['n']} 거절")
        # 항목마다 저장: 중간에 실패해도 이미 적용한 항목이 다시 적용되지 않게
        save()
    save()
    return log


def describe(it: dict) -> str:
    op = it["op"]
    if op == "evidence":
        return f"[근거] {it['id']} +지지 {len(it['supports'])} +반례 {len(it['contradicts'])}: {it['reason']}"
    if op == "new_opinion":
        conf = confidence.confidence(len(it["supports"]), len(it["contradicts"]))
        return f"[새 판단 {conf:.2f}] {it['statement']}"
    if op == "new_procedure":
        return f"[새 절차] {it['trigger']}: {' → '.join(it['rules'])}"
    if op == "observe":
        return f"[관찰] {it['subject']}: {it['summary'][:80]}"
    if op == "invalidate":
        return f"[무효화] {it['id']}: {it['reason']}"
    if op == "revise":
        return f"[수정] {it['id']} → {it['statement'] or ' → '.join(it['rules'])}"
    return str(it)
