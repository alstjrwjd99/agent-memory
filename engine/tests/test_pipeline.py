import json

from amem import export, health, promote, reflect, review
from amem.store import Store

from conftest import FakeLLM, ev, write_events

EPISODE = {"title": "UI 설계 순서", "event": "구현부터 하다 목적 불명확", "action": "사용자/행위/데이터 먼저 정의",
           "result": "화면 구조 결정이 쉬워짐", "project": "acme", "signals": ["correction"], "tags": ["UI작업"]}


def test_quiet_session_skipped_without_llm_call(store, tmp_path):
    write_events(store, "2026-10-12_aaaaaaaa.jsonl", [ev("tool", "Read", "a.md", True), ev("turn", "answer")])
    llm = FakeLLM()
    r = promote.run(store, llm, tmp_path / "claude")
    assert r.skipped_no_signal == 1 and r.llm_calls == 0
    assert promote.pending(store) == []


def test_signal_session_promoted_with_transcript(store, tmp_path):
    claude = tmp_path / "claude"
    proj = claude / "projects" / "-Users-a-ws"
    proj.mkdir(parents=True)
    (proj / "bbbbbbbb-1111.jsonl").write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "화면부터 만들어줘"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "만들었어요"}]}}) + "\n",
        encoding="utf-8",
    )
    write_events(store, "2026-10-12_bbbbbbbb.jsonl", [ev("tool", "Edit", "ui.tsx", True), ev("correction", "아니"), ev("turn", "answer")])
    llm = FakeLLM({"episodes": [EPISODE]})
    r = promote.run(store, llm, claude)
    assert len(r.episodes) == 1
    assert "화면부터 만들어줘" in llm.prompts[0] and "correction" in llm.prompts[0]
    ep = store.get(r.episodes[0])
    assert ep.meta["source"] == {"machine": "mac", "session": "bbbbbbbb", "date": "2026-10-12"}
    assert ep.meta["tags"] == ["상황/UI작업"]


def test_session_that_grew_is_reprocessed_only_for_new_events(store, tmp_path):
    path = write_events(store, "2026-10-12_cccccccc.jsonl", [ev("tool", "Read", ok=True)])
    promote.run(store, FakeLLM(), tmp_path)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev("correction", "아니")) + "\n")
    [(log, start)] = promote.pending(store)
    assert start == 1 and len(log.events) == 2


def test_other_machine_events_are_not_processed_here(store, tmp_path):
    write_events(store, "2026-10-12_dddddddd.jsonl", [ev("correction", "아니")], machine="win-work")
    assert promote.pending(store) == []


def _episodes(store: Store, n: int) -> list[str]:
    return [store.add("experience", {**EPISODE, "title": f"ep{k}"}, "b").id for k in range(n)]


def test_reflect_filters_unknown_ids_and_apply_updates_confidence(store):
    e1, e2, e3 = _episodes(store, 3)
    llm = FakeLLM({
        "evidence_updates": [],
        "new_opinions": [
            {"statement": "UI는 사용자/행위/데이터를 먼저 정의해야 한다", "supports": [e1, e2, "ep_fake"], "contradicts": [], "reason": "2회 반복"},
            {"statement": "근거 없는 판단", "supports": ["ep_fake"], "contradicts": [], "reason": "x"},
        ],
        "new_procedures": [{"trigger": "새 UI 설계", "rules": ["사용자 정의", "행위 정의", "데이터 확인"], "derived_from": [e1, e2], "reason": "반복"}],
        "observations": [{"subject": "acme", "summary": "UI 요구가 자주 바뀜", "sources": [e3]}],
        "invalidations": [{"id": "op_없는것", "reason": "x"}],
    })
    path = reflect.run(store, llm)
    p = json.loads(path.read_text(encoding="utf-8"))
    ops = [it["op"] for it in p["items"]]
    assert ops == ["new_opinion", "new_procedure", "observe"]  # 근거 없는 판단/없는 id 무효화는 버려짐
    assert p["items"][0]["supports"] == [e1, e2]
    # 이미 고려한 episode는 다시 reflect하지 않음
    assert reflect.fresh_episodes(store) == []

    log = review.decide(store, p["id"], accept=True, only={1, 3})
    assert len(log) == 2
    [op] = store.items("opinion")
    assert op.meta["history"][-1]["confidence"] == 0.75  # (2+1)/(2+0+2)
    assert json.loads(path.read_text(encoding="utf-8"))["items"][1]["status"] == "pending"

    # 새 episode가 반박 → confidence 하락, 이력 남음 (삭제 없음)
    (e4,) = _episodes(store, 1)
    llm2 = FakeLLM({"evidence_updates": [{"id": op.id, "supports": [], "contradicts": [e4], "reason": "반례"}],
                    "new_opinions": [], "new_procedures": [], "observations": [], "invalidations": []})
    p2 = json.loads(reflect.run(store, llm2).read_text(encoding="utf-8"))
    review.decide(store, p2["id"], accept=True)
    op = store.get(op.id)
    assert [h["confidence"] for h in op.meta["history"]] == [0.75, 0.6]
    h = health.compute(store)
    assert h["recent_changes"][0]["from"] == 0.75 and h["recent_changes"][0]["to"] == 0.6
    assert "Recent Reflection" in health.render(h)


def test_procedure_needs_two_episodes(store):
    (e1,) = _episodes(store, 1)
    llm = FakeLLM({"evidence_updates": [], "new_opinions": [], "observations": [], "invalidations": [],
                   "new_procedures": [{"trigger": "t", "rules": ["a"], "derived_from": [e1], "reason": "1회뿐"}]})
    p = json.loads(reflect.run(store, llm).read_text(encoding="utf-8"))
    assert p["items"] == []


def test_invalidate_keeps_file_with_status(store):
    op = store.add("opinion", {"statement": "s", "evidence": [], "counter_evidence": []}, "s")
    (e,) = _episodes(store, 1)
    llm = FakeLLM({"evidence_updates": [], "new_opinions": [], "new_procedures": [], "observations": [],
                   "invalidations": [{"id": op.id, "reason": "뒤집힘"}]})
    p = json.loads(reflect.run(store, llm).read_text(encoding="utf-8"))
    review.decide(store, p["id"], accept=True)
    after = store.get(op.id)
    assert after.meta["status"] == "invalidated" and after.meta["valid_to"]


def test_export_threshold_index_block_and_scope_cleanup(store, tmp_path):
    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "MEMORY.md").write_text("# Memory Index\n\n- [기존](x.md) — 유지\n", encoding="utf-8")
    strong = store.add("opinion", {"statement": "강한 판단", "evidence": ["a", "b"], "counter_evidence": []}, "s")
    store.add("opinion", {"statement": "약한 판단", "evidence": ["a"], "counter_evidence": []}, "s")  # 0.67 < 0.7
    lines = export.run(store, "personal", mem, 0.7)
    assert len(lines) == 1 and (mem / f"amem_personal_{strong.id}.md").exists()
    idx = (mem / "MEMORY.md").read_text(encoding="utf-8")
    assert "- [기존](x.md) — 유지" in idx and "<!-- amem:personal:begin -->" in idx

    # work scope 파일은 personal export가 지우지 않음
    (mem / "amem_op_work.md").write_text("---\namem_scope: work\n---\nx\n", encoding="utf-8")
    strong.meta["status"] = "superseded"
    store.save(strong)
    export.run(store, "personal", mem, 0.7)
    assert not (mem / f"amem_personal_{strong.id}.md").exists() and (mem / "amem_op_work.md").exists()
    assert (mem / "MEMORY.md").read_text(encoding="utf-8").count("amem:personal:begin") == 1


def test_memory_dir_encoding_mac_and_windows(tmp_path):
    assert export.memory_dir(tmp_path, "/Users/a").name == "memory"
    assert export.memory_dir(tmp_path, "/Users/a").parent.name == "-Users-a"
    assert export.memory_dir(tmp_path, "C:\\Users\\jung").parent.name == "C--Users-jung"


# ---- 코드 리뷰 지적 회귀 테스트 ----

def _reflect_with(store, **parts):
    base = {"evidence_updates": [], "new_opinions": [], "new_procedures": [], "observations": [], "invalidations": []}
    return json.loads(reflect.run(store, FakeLLM({**base, **parts})).read_text(encoding="utf-8"))


def test_duplicate_and_contradictory_citations_do_not_inflate_confidence(store):
    e1, e2 = _episodes(store, 2)
    p = _reflect_with(
        store,
        new_opinions=[{"statement": "s", "supports": [e1, e1, e1, e2], "contradicts": [e2], "reason": "r"}],
        new_procedures=[{"trigger": "t", "rules": ["a"], "derived_from": [e1, e1], "reason": "중복으로 2개 흉내"}],
    )
    assert [it["op"] for it in p["items"]] == ["new_opinion"]
    assert p["items"][0]["supports"] == [e1] and p["items"][0]["contradicts"] == []


def test_low_confidence_can_recover_and_invalidated_is_untouched(store):
    op = store.add("opinion", {"statement": "s", "evidence": [], "counter_evidence": []}, "s")
    dead = store.add("opinion", {"statement": "d", "evidence": [], "counter_evidence": [], "status": "invalidated"}, "d")
    c1, c2 = _episodes(store, 2)
    p = _reflect_with(store, evidence_updates=[{"id": op.id, "supports": [], "contradicts": [c1, c2], "reason": "반례"}])
    review.decide(store, p["id"], accept=True)
    assert store.get(op.id).meta["status"] == "low_confidence"  # 1/4 = 0.25
    s1, s2, s3 = _episodes(store, 3)
    p = _reflect_with(store, evidence_updates=[{"id": op.id, "supports": [s1, s2, s3], "contradicts": [], "reason": "지지"}])
    assert p["items"], "low_confidence 항목도 근거 갱신 대상이어야 함"
    review.decide(store, p["id"], accept=True)
    assert store.get(op.id).meta["status"] == "active"  # 4/7 = 0.57
    assert dead.id not in {i.id for i in reflect._active(store, "opinion")}


def test_export_same_id_in_two_scopes_does_not_collide(tmp_path):
    mem = tmp_path / "mem"
    personal, work = Store(tmp_path / "p", "mac"), Store(tmp_path / "w", "mac")
    a = personal.add("opinion", {"statement": "개인", "evidence": ["a", "b"], "counter_evidence": []}, "s")
    b = work.add("opinion", {"statement": "업무", "evidence": ["a", "b"], "counter_evidence": []}, "s")
    assert a.id == b.id
    export.run(personal, "personal", mem, 0.7)
    export.run(work, "work", mem, 0.7)
    assert "개인" in (mem / f"amem_personal_{a.id}.md").read_text(encoding="utf-8")
    assert "업무" in (mem / f"amem_work_{b.id}.md").read_text(encoding="utf-8")


class Boom:
    def __init__(self):
        self.calls = 0

    def json(self, prompt, schema):
        self.calls += 1
        if self.calls == 1:
            return {"episodes": [EPISODE]}
        raise KeyboardInterrupt  # LLMError가 아닌 예외로 중단


def test_promote_saves_progress_even_if_interrupted(store, tmp_path):
    write_events(store, "2026-10-12_aaaaaaaa.jsonl", [ev("correction", "아니")])
    write_events(store, "2026-10-12_bbbbbbbb.jsonl", [ev("correction", "아니")])
    try:
        promote.run(store, Boom(), tmp_path)
    except KeyboardInterrupt:
        pass
    assert len(store.items("experience")) == 1
    assert [log.session for log, _ in promote.pending(store)] == ["bbbbbbbb"]


def test_malformed_episode_is_skipped_not_crashing(store, tmp_path):
    write_events(store, "2026-10-12_aaaaaaaa.jsonl", [ev("correction", "아니")])
    r = promote.run(store, FakeLLM({"episodes": [{"title": "필드 누락"}, EPISODE]}), tmp_path)
    assert len(r.episodes) == 1 and promote.pending(store) == []


def test_shrunk_session_file_restarts_and_prompt_lists_existing_episodes(store, tmp_path):
    path = write_events(store, "2026-10-12_aaaaaaaa.jsonl", [ev("correction", "아니"), ev("turn", "answer")])
    promote.run(store, FakeLLM({"episodes": [EPISODE]}), tmp_path)
    path.write_text(json.dumps(ev("correction", "다시해")) + "\n", encoding="utf-8")  # 1줄로 줄어듦
    [(log, start)] = promote.pending(store)
    assert start == 0
    llm = FakeLLM({"episodes": []})
    promote.run(store, llm, tmp_path)
    assert "UI 설계 순서" in llm.prompts[0]


def test_cli_only_empty_is_rejected(store, tmp_path, monkeypatch):
    import pytest
    from amem import cli, config
    monkeypatch.setenv("AMEM_CONFIG", str(tmp_path / "c.yaml"))
    config.write_default(tmp_path / "c.yaml", "mac", str(store.root), None)
    with pytest.raises(SystemExit, match="항목 번호"):
        cli.main(["apply", "x", "--only", ""])
