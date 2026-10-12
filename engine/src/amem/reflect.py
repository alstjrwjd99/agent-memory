"""reflect: 새 episode + 기존 판단을 보고 판단 변화 '제안'을 만든다 (적용은 사용자 승인 후)."""
from __future__ import annotations

import json
from pathlib import Path

from . import confidence, schema
from .llm import Backend
from .store import Item, Store, now_iso, today

PROMPT = """너는 에이전트 기억 시스템의 reflect 단계다. 경험(episode)에서 판단(opinion)과 행동 규칙(procedure)을 만든다.

가장 중요한 기준: **일반 개발자가 이미 아는 상식은 기억할 가치가 없다.**
"테스트가 중요하다", "운영 데이터로 e2e 확인", "기존 함수를 재사용하라", "원문을 보존하라" 같은 일반론은 만들지 마라.
기억할 가치가 있는 것은 둘뿐이다:
  (a) 이 프로젝트/도메인에서만 성립하는 구체적 지식 (어떤 대상이 어떤 조건에서 어떻게 동작하는지, 왜 그렇게 해야 하는지)
  (b) 상식이지만 이 작업에서 실제로 2번 이상 놓친 것. 이 경우 놓친 사례를 why_not_obvious에 구체적으로 적어라.
판단 문장(statement)에는 반드시 구체적 대상과 조건을 넣어라. 나쁜 예: "로직 수정 후 기존 데이터도 확인하는 것이 중요하다".
좋은 예: "acme-billing에서 요금 계산을 고치면 할인 필드가 빈 기존 계약은 레거시 기본 요율 폴백을 타므로, 운영의 기존 계약으로 청구서를 다시 뽑아 확인한다".

규칙:
- 근거 없는 판단을 만들지 마라. 모든 제안은 아래 episode id를 근거로 인용해야 한다.
- 기존 opinion/procedure를 새 episode가 지지하면 evidence_updates.supports, 반박하면 contradicts에 넣어라.
- 새 opinion: 검증 가능한 판단 한 문장 + context(어느 프로젝트/대상/상황에서) + why_not_obvious(왜 상식이 아닌가, 또는 실제로 놓친 사례들). why_not_obvious를 구체적으로 못 쓰면 만들지 마라.
- 새 procedure는 반복된 작업 방식: trigger(언제) + rules(순서 있는 단계, 각 단계에 구체적 대상/명령/확인값) + why_not_obvious. 같은 패턴이 episode 2개 이상에서 보일 때만. 판단보다 절차가 실제 행동을 더 잘 바꾼다.
- observations: 특정 대상(프로젝트, 사용자 작업 스타일, 시스템)에 대한 요약. subject는 짧은 이름.
- invalidations: 근거가 명확히 뒤집혀 더 이상 유효하지 않은 기존 항목만.
- revisions: 기존 opinion/procedure의 방향은 맞지만 표현이나 범위를 새 episode에 맞게 다듬어야 할 때. opinion은 statement, procedure는 rules를 채우고 supports에 근거 episode를 넣어라. 새 판단을 따로 만들기보다 기존 것을 다듬는 쪽을 우선한다.
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


def _explained(text: str) -> bool:
    """why_not_obvious가 실질적인 설명인지 (빈 값/형식적 문구 제외)."""
    t = (text or "").strip()
    return len(t) >= 15 and t not in ("없음", "N/A", "-")


def _considered(store: Store) -> set[str]:
    """이미 reflect에 들어간 episode (모든 PC의 proposal 파일 기준 → sync 충돌 없음).
    superseded(다시 돌리기로 한) 제안은 제외 → 그 episode들은 다시 reflect 대상."""
    seen: set[str] = set()
    d = store.root / "proposals"
    for f in d.glob("*.json") if d.exists() else []:
        p = json.loads(f.read_text(encoding="utf-8"))
        if p.get("status") != "superseded":
            seen.update(p.get("considered", []))
    return seen


def supersede(store: Store, pid: str) -> int:
    """제안을 폐기하고 그 episode들을 다시 reflect 대상으로. 이미 적용한 항목이 있으면 거부."""
    path = store.root / "proposals" / f"{pid}.json"
    if not path.exists():
        raise SystemExit(f"제안 없음: {pid}")
    p = json.loads(path.read_text(encoding="utf-8"))
    if any(it["status"] == "applied" for it in p["items"]):
        raise SystemExit(f"{pid}에 이미 적용한 항목이 있어 다시 돌릴 수 없음 (중복 판단 방지)")
    for it in p["items"]:
        if it["status"] == "pending":
            it["status"] = "superseded"
    p["status"] = "superseded"
    p["superseded_at"] = now_iso()
    path.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return len(p.get("considered", []))


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
        # 상식 필터: 왜 상식이 아닌지 설명 못 하면 버림
        if s and _explained(o.get("why_not_obvious", "")):
            items.append({"op": "new_opinion", "statement": o["statement"], "context": o.get("context", ""),
                          "why_not_obvious": o["why_not_obvious"], "supports": s, "contradicts": c, "reason": o["reason"]})
    for p in proposal.get("new_procedures", []):
        d = ok(p["derived_from"])
        # 절차는 반복된 패턴이어야 하므로 근거 episode 2개 이상만
        if len(d) >= 2 and p["rules"] and _explained(p.get("why_not_obvious", "")):
            items.append({"op": "new_procedure", "trigger": p["trigger"], "rules": p["rules"], "why_not_obvious": p["why_not_obvious"],
                          "derived_from": d, "reason": p["reason"]})
    for ob in proposal.get("observations", []):
        src = ok(ob["sources"])
        if src:
            items.append({"op": "observe", "subject": ob["subject"], "summary": ob["summary"], "sources": src})
    for inv in proposal.get("invalidations", []):
        if inv["id"] in item_ids:
            items.append({"op": "invalidate", "id": inv["id"], "reason": inv["reason"]})
    for rv in proposal.get("revisions", []):
        s = ok(rv["supports"])
        is_op, is_pr = rv["id"].startswith("op_"), rv["id"].startswith("pr_")
        if rv["id"] in item_ids and s and ((is_op and rv["statement"].strip()) or (is_pr and rv["rules"])):
            items.append({"op": "revise", "id": rv["id"], "statement": rv["statement"] if is_op else "",
                          "rules": rv["rules"] if is_pr else [], "supports": s, "reason": rv["reason"]})
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
