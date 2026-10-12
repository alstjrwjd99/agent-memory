"""원칙(heuristic) 층: 경험 → 작은 판단 원칙 → (상황마다) 판단.

판단은 저장하지 않는다. 오래 남길 것은 원칙이고, 판단은 지금 상황 + 원칙으로 매번 조합한다.
원칙이 늘어나는 것을 막기 위해 새로 만들기 전에 기존 원칙과 먼저 합친다:
  같음 → 근거 +1 / 비슷함 → 일반화 / 충돌 → 반례 또는 예외 / 정말 새로움 → 새 원칙
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import confidence, schema
from .llm import Backend
from .store import Item, Store, now_iso

BATCH = 8
LEVELS = ("specific", "general")
SCOPES = ("project", "global")

DISTILL_PROMPT = """너는 한 사람의 경험에서 "작은 판단 원칙(heuristic)"을 정리하는 역할이다.
원칙은 불확실한 상황에서 판단에 무게를 실어주는 짧은 문장이다. if-then 규칙이나 명언이 아니다.
판단 자체는 저장하지 않는다. 나중에 새 상황에서 여러 원칙을 조합해 판단을 만든다.

가장 중요한 규칙: **원칙을 늘리지 마라.** 새 경험마다 아래 순서로 처리하라.
1. 기존 원칙과 같은 이야기면 → supports (근거 추가)
2. 비슷하지만 기존 문장이 너무 좁으면 → generalizations (문장/조건을 넓혀 다시 씀. 원래 의미를 포함해야 함)
3. 기존 원칙과 맞지 않으면 → conflicts (kind=counterexample: 원칙이 틀린 사례 / kind=exception: 원칙의 예외 조건을 unless_add에 추가)
4. 위에 해당하지 않는 정말 새로운 패턴만 → new
경험 하나에서 new는 보통 0~1개다. 같은 배치 안의 여러 경험이 같은 패턴이면 new 하나에 episodes를 여러 개 넣어라.

원칙 필드:
- statement: 원칙 한 문장 (구체적인 대상보다 판단의 핵심을 담되, 상식적 일반론이면 만들지 마라)
- when: 이 원칙이 떠올라야 하는 상황 (자연어, 구체적으로)
- unless: 이 원칙을 적용하면 안 되는 예외 (모르면 빈 문자열)
- why: 왜 이 원칙이 필요한가. 경험에서 실제로 무엇이 틀렸는지 (상식이 아닌 이유)
- scope: 이 프로젝트에서만 성립하면 "project", 다른 프로젝트에서도 통하면 "global"
- level: 특정 대상/도구에 묶이면 "specific", 여러 상황에 통하는 원리면 "general"

일반론("테스트가 중요하다", "원문을 보존하라")은 만들지 마라. 실제 경험에서 무엇이 어떻게 틀렸는지가 why에 들어가야 한다.
기존 원칙 id와 아래 경험 id만 인용하라. 한국어로.

## 기존 원칙
{existing}

## 새 경험 (프로젝트: {project})
{episodes}
"""

ABSTRACT_PROMPT = """아래는 한 사람의 작은 판단 원칙 목록이다. 비슷한 구체 원칙들을 상위 일반 원칙으로 묶어라.

예: "Pa 단위를 확인한다", "ppm과 %를 구분한다", "개월과 연을 확인한다"
  → 상위 원칙 "숫자의 의미는 값·단위·조건을 하나의 원자 값으로 취급한다"

규칙:
- 실제로 같은 원리를 공유하는 2개 이상만 묶어라. 억지로 묶지 마라. 묶을 게 없으면 빈 배열.
- 상위 원칙은 자식들의 공통 원리를 담고, 다른 프로젝트에서도 떠올릴 수 있게 when을 일반적으로 써라.
- why에는 자식 원칙들의 실제 사례가 왜 같은 원리인지 써라.
- children에는 아래 원칙 id만. 한국어로.

## 원칙 목록
{heuristics}
"""


def active_or_candidate(store: Store) -> list[Item]:
    return [i for i in store.items("heuristic") if i.meta.get("status") in ("active", "candidate")]


def fmt(i: Item) -> str:
    m = i.meta
    unless = f" / 예외: {m['unless']}" if m.get("unless") else ""
    return (f"- {i.id} [{m.get('level')}/{m.get('scope')}] 근거 {len(m.get('evidence') or [])} 반례 {len(m.get('counter_evidence') or [])}\n"
            f"  원칙: {m.get('statement')}\n  언제: {m.get('when')}{unless}")


def _fmt_ep(e: Item) -> str:
    m = e.meta
    return f"- {e.id} {m.get('title')}\n  상황: {m.get('event')}\n  행동: {m.get('action')}\n  결과: {m.get('result')}"


def _merge(xs, ys):
    return list(dict.fromkeys([*(xs or []), *ys]))


def _history(meta: dict, note: str) -> None:
    meta.setdefault("history", []).append({"at": now_iso(), "support": len(meta.get("evidence") or []),
                                           "counter": len(meta.get("counter_evidence") or []),
                                           "confidence": round(confidence.of(meta), 3), "note": note})


@dataclass
class DistillResult:
    episodes: int = 0
    llm_calls: int = 0
    new: list[str] = field(default_factory=list)
    supported: int = 0
    generalized: int = 0
    conflicts: int = 0
    merged: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def apply_distill(store: Store, out: dict, ep_ids: set[str], project: str, res: DistillResult) -> None:
    """LLM 결과를 바로 반영 (다음 배치가 갱신된 원칙을 보고 합칠 수 있게). 새 원칙은 candidate."""
    known = {i.id: i for i in active_or_candidate(store)}
    ok = lambda ids: list(dict.fromkeys(x for x in ids if x in ep_ids))  # noqa: E731
    for s in out.get("supports", []):
        h, eps = known.get(s["id"]), ok(s["episodes"])
        if h and eps:
            h.meta["evidence"] = _merge(h.meta.get("evidence"), eps)
            _history(h.meta, f"근거 추가: {s['reason']}")
            store.save(h)
            res.supported += 1
    for g in out.get("generalizations", []):
        h, eps = known.get(g["id"]), ok(g["episodes"])
        if h and g["statement"].strip():
            h.meta.setdefault("versions", []).append({"at": h.meta.get("updated_at"), "statement": h.meta.get("statement"), "when": h.meta.get("when")})
            h.meta.update(statement=g["statement"], when=g["when"], unless=g["unless"] or h.meta.get("unless", ""), why=g["why"] or h.meta.get("why", ""))
            h.meta["evidence"] = _merge(h.meta.get("evidence"), eps)
            h.body = g["statement"]
            _history(h.meta, f"일반화: {g['reason']}")
            store.save(h)
            res.generalized += 1
    for c in out.get("conflicts", []):
        h = known.get(c["id"])
        if not h or c["episode"] not in ep_ids:
            continue
        if c["kind"] == "exception" and c["unless_add"].strip():
            h.meta["unless"] = "; ".join(x for x in [h.meta.get("unless", ""), c["unless_add"].strip()] if x)
            h.meta["evidence"] = _merge(h.meta.get("evidence"), [c["episode"]])
            note = f"예외 추가: {c['reason']}"
        else:
            h.meta["counter_evidence"] = _merge(h.meta.get("counter_evidence"), [c["episode"]])
            note = f"반례: {c['reason']}"
        _history(h.meta, note)
        store.save(h)
        res.conflicts += 1
    for n in out.get("new", []):
        eps = ok(n["episodes"])
        if not eps or not n["statement"].strip() or len(n["why"].strip()) < 15:
            continue  # 근거나 이유 없는 원칙은 버림
        meta = {"statement": n["statement"], "when": n["when"], "unless": n["unless"], "why": n["why"],
                "scope": n["scope"] if n["scope"] in SCOPES else "project",
                "level": n["level"] if n["level"] in LEVELS else "specific",
                "project": project, "evidence": eps, "counter_evidence": [], "status": "candidate", "parent": None}
        _history(meta, "새 원칙")
        res.new.append(store.add("heuristic", meta, n["statement"]).id)


def distill(store: Store, llm: Backend, episodes: list[Item], project: str, batch: int = BATCH) -> DistillResult:
    res = DistillResult(episodes=len(episodes))
    state = store.load_state("distill")
    done = set(state.get("episodes", []))
    todo = [e for e in episodes if e.id not in done]
    try:
        for start in range(0, len(todo), batch):
            chunk = todo[start : start + batch]
            prompt = DISTILL_PROMPT.format(
                existing="\n".join(fmt(i) for i in active_or_candidate(store)) or "- (아직 없음)",
                project=project, episodes="\n".join(_fmt_ep(e) for e in chunk))
            try:
                out = llm.json(prompt, schema.DISTILL)
                res.llm_calls += 1
            except Exception as e:
                res.errors.append(f"batch {start // batch + 1}: {e}")
                continue
            apply_distill(store, out, {e.id for e in chunk}, project, res)
            done.update(e.id for e in chunk)
    finally:
        store.save_state("distill", {"episodes": sorted(done)})
    return res


def abstract(store: Store, llm: Backend, res: DistillResult | None = None) -> DistillResult:
    """구체 원칙들을 상위 원칙으로 묶음. 자식은 지우지 않고 parent로 연결 (구체 사례로 남음)."""
    res = res or DistillResult()
    roots = [i for i in active_or_candidate(store) if not i.meta.get("parent")]
    if len(roots) < 2:
        return res
    out = llm.json(ABSTRACT_PROMPT.format(heuristics="\n".join(fmt(i) for i in roots)), schema.ABSTRACT)
    res.llm_calls += 1
    by_id = {i.id: i for i in roots}
    for m in out.get("merges", []):
        kids = [by_id[c] for c in dict.fromkeys(m["children"]) if c in by_id]
        if len(kids) < 2 or not m["statement"].strip():
            continue
        projects = {k.meta.get("project") for k in kids}
        meta = {"statement": m["statement"], "when": m["when"], "unless": m["unless"], "why": m["why"],
                "scope": "global" if len(projects) > 1 or any(k.meta.get("scope") == "global" for k in kids) else "project",
                "level": "general", "project": next(iter(projects)) if len(projects) == 1 else None,
                # 상위 원칙의 근거 = 자식들 근거의 합집합 (경험 단위로 세므로 중복 없음)
                "evidence": _merge([], [e for k in kids for e in k.meta.get("evidence") or []]),
                "counter_evidence": _merge([], [e for k in kids for e in k.meta.get("counter_evidence") or []]),
                "children": [k.id for k in kids], "status": "candidate", "parent": None}
        _history(meta, f"압축: {m['reason']}")
        parent = store.add("heuristic", meta, m["statement"])
        for k in kids:
            k.meta["parent"] = parent.id
            store.save(k)
        res.merged.append(parent.id)
        by_id = {i: v for i, v in by_id.items() if v not in kids}
    return res


def tree(store: Store, statuses=("active", "candidate")) -> list[tuple[Item, list[Item]]]:
    """최상위 원칙과 그 자식들 (근거 많은 순)."""
    items = [i for i in store.items("heuristic") if i.meta.get("status") in statuses]
    by_parent: dict[str | None, list[Item]] = {}
    for i in items:
        by_parent.setdefault(i.meta.get("parent"), []).append(i)
    key = lambda i: (-len(i.meta.get("evidence") or []), i.id)  # noqa: E731
    return [(r, sorted(by_parent.get(r.id, []), key=key)) for r in sorted(by_parent.get(None, []), key=key)]


def accept(store: Store, ids: list[str] | None = None) -> int:
    """후보 원칙을 활성화 (ids 없으면 전부)."""
    n = 0
    for i in store.items("heuristic"):
        if i.meta.get("status") == "candidate" and (ids is None or i.id in ids):
            i.meta["status"] = "active"
            store.save(i)
            n += 1
    return n
