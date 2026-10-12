"""reflect: 새 episode + 기존 판단을 보고 판단 변화 '제안'을 만든다 (적용은 사용자 승인 후)."""
from __future__ import annotations

import json
from pathlib import Path

from . import confidence, schema
from .llm import Backend
from .store import Item, Store, now_iso, today

PROMPT = """너는 에이전트 기억 시스템의 reflect 단계다. 경험(episode)에서 판단(opinion)과 행동 규칙(procedure)을 만든다.

규칙:
- 근거 없는 판단을 만들지 마라. 모든 제안은 아래 episode id를 근거로 인용해야 한다.
- 기존 opinion/procedure를 새 episode가 지지하면 evidence_updates.supports, 반박하면 contradicts에 넣어라.
- 새 opinion은 "~하는 것이 낫다/중요하다" 같은 검증 가능한 판단 한 문장. 단순 사실이나 취향은 opinion이 아니다.
- 새 procedure는 반복된 작업 방식: trigger(언제) + rules(순서 있는 단계). 같은 패턴이 episode 2개 이상에서 보일 때만.
- observations: 특정 대상(프로젝트, 사용자 작업 스타일, 시스템)에 대한 요약. subject는 짧은 이름.
- invalidations: 근거가 명확히 뒤집혀 더 이상 유효하지 않은 기존 항목만.
- confidence 숫자는 만들지 마라 (시스템이 근거 개수로 계산한다).
- 확실하지 않으면 제안하지 마라. 빈 배열도 정상이다. 한국어로.

## 새 episode
{episodes}

## 기존 opinion
{opinions}

## 기존 procedure
{procedures}

## 기존 observation
{observations}
"""


def _considered(store: Store) -> set[str]:
    """이미 reflect에 들어간 episode (모든 PC의 proposal 파일 기준 → sync 충돌 없음)."""
    seen: set[str] = set()
    d = store.root / "proposals"
    for f in d.glob("*.json") if d.exists() else []:
        seen.update(json.loads(f.read_text(encoding="utf-8")).get("considered", []))
    return seen


def fresh_episodes(store: Store) -> list[Item]:
    seen = _considered(store)
    return [e for e in store.items("experience") if e.id not in seen and e.meta.get("status") == "active"]


def _fmt_ep(e: Item) -> str:
    m = e.meta
    return f"- {e.id} [{m.get('project')}] {m.get('title')}: 상황={m.get('event')} / 행동={m.get('action')} / 결과={m.get('result')}"


def _fmt_judgment(i: Item) -> str:
    text = i.meta.get("statement") or f"{i.meta.get('trigger')}: {' → '.join(i.meta.get('rules') or [])}"
    flag = " [low_confidence]" if i.meta.get("status") == "low_confidence" else ""
    return f"- {i.id}{flag} (conf {confidence.of(i.meta):.2f}, 지지 {len(i.meta.get('evidence') or [])}, 반례 {len(i.meta.get('counter_evidence') or [])}) {text}"


def _active(store: Store, kind: str) -> list[Item]:
    # low_confidence도 포함: 새 근거로 다시 살아날 수 있어야 한다
    return [i for i in store.items(kind) if i.meta.get("status") in ("active", "low_confidence")]


def _clean(proposal: dict, ep_ids: set[str], item_ids: set[str]) -> list[dict]:
    """존재하지 않는 id 인용을 걸러내고, 근거 없는 제안은 버린다."""
    def ok(ids: list[str]) -> list[str]:
        # 존재하는 episode만, 중복 제거 (중복 인용으로 confidence 부풀리기 방지)
        return list(dict.fromkeys(i for i in ids if i in ep_ids))

    def split(sup: list[str], con: list[str]) -> tuple[list[str], list[str]]:
        # 같은 episode가 지지와 반례에 동시에 오면 둘 다에서 뺀다 (모순)
        s, c = ok(sup), ok(con)
        both = set(s) & set(c)
        return [i for i in s if i not in both], [i for i in c if i not in both]

    items: list[dict] = []
    for u in proposal.get("evidence_updates", []):
        s, c = split(u["supports"], u["contradicts"])
        if u["id"] in item_ids and (s or c):
            items.append({"op": "evidence", "id": u["id"], "supports": s, "contradicts": c, "reason": u["reason"]})
    for o in proposal.get("new_opinions", []):
        s, c = split(o["supports"], o["contradicts"])
        if s:
            items.append({"op": "new_opinion", "statement": o["statement"], "supports": s, "contradicts": c, "reason": o["reason"]})
    for p in proposal.get("new_procedures", []):
        d = ok(p["derived_from"])
        # 절차는 반복된 패턴이어야 하므로 근거 episode 2개 이상만
        if len(d) >= 2 and p["rules"]:
            items.append({"op": "new_procedure", "trigger": p["trigger"], "rules": p["rules"], "derived_from": d, "reason": p["reason"]})
    for ob in proposal.get("observations", []):
        src = ok(ob["sources"])
        if src:
            items.append({"op": "observe", "subject": ob["subject"], "summary": ob["summary"], "sources": src})
    for inv in proposal.get("invalidations", []):
        if inv["id"] in item_ids:
            items.append({"op": "invalidate", "id": inv["id"], "reason": inv["reason"]})
    for n, it in enumerate(items, 1):
        it["n"] = n
        it["status"] = "pending"
    return items


def run(store: Store, llm: Backend, dry_run: bool = False) -> Path | None:
    eps = fresh_episodes(store)
    if not eps:
        return None
    ops, prs, obs = _active(store, "opinion"), _active(store, "procedure"), _active(store, "observation")
    prompt = PROMPT.format(
        episodes="\n".join(_fmt_ep(e) for e in eps),
        opinions="\n".join(_fmt_judgment(i) for i in ops) or "- (없음)",
        procedures="\n".join(_fmt_judgment(i) for i in prs) or "- (없음)",
        observations="\n".join(f"- {i.id} {i.meta.get('subject')}: {i.body.strip()[:200]}" for i in obs) or "- (없음)",
    )
    if dry_run:
        print(prompt)
        return None
    raw = llm.json(prompt, schema.REFLECTION)
    items = _clean(raw, {e.id for e in eps} | {e.id for e in store.items("experience")}, {i.id for i in ops + prs + obs})
    d = store.root / "proposals"
    d.mkdir(parents=True, exist_ok=True)
    base = f"{today().replace('-', '')}_{store.machine}_"
    n = 1
    while (d / f"{base}{n:03d}.json").exists():
        n += 1
    pid = f"{base}{n:03d}"
    path = d / f"{pid}.json"
    data = {"id": pid, "created_at": now_iso(), "machine": store.machine, "status": "pending", "considered": [e.id for e in eps], "items": items}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return path
