from amem import heuristics
from amem.store import Store

from conftest import FakeLLM

EMPTY = {"supports": [], "generalizations": [], "conflicts": [], "new": []}
WHY = "기본값이 원문을 덮어 허용폭이 3배 어긋났는데 에러가 없었다"


def _eps(store: Store, n: int) -> list:
    return [store.add("experience", {"title": f"t{k}", "event": "e", "action": "a", "result": "r", "project": "acme"}, "b") for k in range(n)]


def _new(statement, eps, **kw):
    return {"statement": statement, "when": kw.get("when", "외부 값 읽을 때"), "unless": "", "why": kw.get("why", WHY),
            "scope": kw.get("scope", "project"), "level": kw.get("level", "specific"), "episodes": eps}


def test_merge_before_create_across_batches(store):
    e = _eps(store, 4)
    llm = FakeLLM(
        {**EMPTY, "new": [_new("기본값은 원문이 비었을 때만", [e[0].id, e[1].id])]},
    )
    r1 = heuristics.distill(store, llm, e[:2], "acme", batch=2)
    [h] = store.items("heuristic")
    assert h.meta["status"] == "candidate" and h.meta["evidence"] == [e[0].id, e[1].id]
    # 두 번째 실행: 기존 원칙을 보고 새로 만들지 않고 근거 추가 + 예외 추가
    llm.responses = [{**EMPTY, "supports": [{"id": h.id, "episodes": [e[2].id, "ep_fake"], "reason": "같은 패턴"}],
                      "conflicts": [{"id": h.id, "episode": e[3].id, "kind": "exception", "unless_add": "더 최신 승인값이 있으면", "reason": "5년 전 문서"}]}]
    r2 = heuristics.distill(store, llm, e, "acme", batch=2)
    assert "기존 원칙" in llm.prompts[1] and h.id in llm.prompts[1]
    assert r1.new and not r2.new and r2.supported == 1 and r2.conflicts == 1
    h = store.get(h.id)
    assert h.meta["evidence"] == [e[0].id, e[1].id, e[2].id, e[3].id]
    assert "최신 승인값" in h.meta["unless"]
    # 이미 정리한 경험은 다시 보내지 않음
    assert all(x.id not in llm.prompts[1] for x in e[:2])


def test_new_without_reason_or_evidence_is_dropped(store):
    e = _eps(store, 1)
    llm = FakeLLM({**EMPTY, "new": [_new("일반론", [e[0].id], why="중요함"), _new("근거 없음", ["ep_x"])]})
    r = heuristics.distill(store, llm, e, "acme")
    assert r.new == [] and store.items("heuristic") == []


def test_generalize_keeps_previous_version(store):
    e = _eps(store, 2)
    heuristics.distill(store, FakeLLM({**EMPTY, "new": [_new("Pa 단위를 확인한다", [e[0].id])]}), e[:1], "acme")
    [h] = store.items("heuristic")
    heuristics.distill(store, FakeLLM({**EMPTY, "generalizations": [{"id": h.id, "statement": "값·단위·조건은 한 묶음", "when": "수치 변환", "unless": "", "why": "", "episodes": [e[1].id], "reason": "ppm도 같음"}]}), e, "acme")
    h = store.get(h.id)
    assert h.meta["statement"] == "값·단위·조건은 한 묶음" and h.meta["versions"][0]["statement"] == "Pa 단위를 확인한다"
    assert h.meta["why"] == WHY  # 빈 why는 기존 것 유지


def test_abstract_links_children_and_unions_evidence(store):
    e = _eps(store, 3)
    heuristics.distill(store, FakeLLM({**EMPTY, "new": [_new("Pa 확인", [e[0].id]), _new("ppm 확인", [e[1].id, e[2].id]), _new("배포 확인", [e[2].id])]}), e, "acme")
    by = {i.meta["statement"]: i.id for i in store.items("heuristic")}
    r = heuristics.abstract(store, FakeLLM({"merges": [
        {"children": [by["Pa 확인"], by["ppm 확인"], by["Pa 확인"]], "statement": "값·단위·조건은 한 원자 값", "when": "외부 수치", "unless": "", "why": "둘 다 단위 오해", "reason": "r"},
        {"children": [by["배포 확인"]], "statement": "혼자는 안 묶임", "when": "", "unless": "", "why": "", "reason": "r"},
    ]}))
    assert len(r.merged) == 1
    parent = store.get(r.merged[0])
    assert parent.meta["level"] == "general" and set(parent.meta["children"]) == {by["Pa 확인"], by["ppm 확인"]}
    assert parent.meta["evidence"] == [e[0].id, e[1].id, e[2].id]
    roots = heuristics.tree(store)
    assert [r.id for r, _ in roots] == [parent.id, by["배포 확인"]]
    assert {k.id for k in roots[0][1]} == {by["Pa 확인"], by["ppm 확인"]}
    assert heuristics.accept(store) == 4 and all(i.meta["status"] == "active" for i in store.items("heuristic"))
