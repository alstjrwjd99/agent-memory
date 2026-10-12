import json
import subprocess
from datetime import date

from amem import config, recall, reflect, review, vcs
from amem.store import Store

from conftest import FakeLLM


def _ep(store, title, project="acme", time="2026-10-01", **kw):
    return store.add("experience", {"title": title, "event": kw.get("event", ""), "action": "", "result": kw.get("result", ""),
                                    "project": project, "time": time}, title)


def test_tokens_korean_bigrams_match_with_particles():
    assert "화면" in recall.tokens("화면을 설계")
    assert "react" in recall.tokens("React 컴포넌트")
    assert "해줘" not in recall.tokens("해줘")


def test_recall_ranks_relevant_and_respects_status(store):
    ui = _ep(store, "UI 화면 설계는 사용자 정의부터")
    _ep(store, "배포 파이프라인 캐시 문제", project="infra")
    op = store.add("opinion", {"statement": "UI 화면은 사용자와 행위를 먼저 정의해야 한다", "evidence": [ui.id], "counter_evidence": []}, "s")
    dead = store.add("opinion", {"statement": "UI 화면은 구현부터 한다", "evidence": [], "counter_evidence": [], "status": "invalidated"}, "s")
    hits = recall.recall(store, "화면 설계 어떻게 해?", today=date(2026, 10, 12))
    ids = [h.item.id for h in hits]
    assert op.id in ids and ui.id in ids and dead.id not in ids
    assert all("배포" not in str(h.item.meta.get("title")) for h in hits)
    assert "판단(conf" in recall.render(hits)


def test_link_expansion_pulls_judgment_via_episode(store):
    ep = _ep(store, "쿠버네티스 롤백 실패", event="helm 롤백")
    op = store.add("opinion", {"statement": "배포 전에 스테이징 검증이 낫다", "evidence": [ep.id], "counter_evidence": []}, "s")
    hits = {h.item.id: h for h in recall.recall(store, "helm 롤백", today=date(2026, 10, 12))}
    assert op.id in hits and "경유" in hits[op.id].why[0]


def test_project_boost_from_cwd_windows_path(store):
    a = _ep(store, "테스트 전략 정리", project="acme")
    b = _ep(store, "테스트 전략 정리", project="other")
    hits = recall.recall(store, "테스트 전략", cwd="C:\\work\\acme\\api", today=date(2026, 10, 12))
    assert hits[0].item.id == a.id and "같은 프로젝트" in hits[0].why
    scores = {h.item.id: h.score for h in recall.recall(store, "테스트 전략", cwd="", today=date(2026, 10, 12), k=5)}
    boosted = {h.item.id: h.score for h in hits}
    assert boosted[a.id] > scores.get(a.id, 0)  # 같은 프로젝트 가중


def test_particles_alone_do_not_match(store):
    _ep(store, "서버에서 배포하는 방법")
    assert recall.recall(store, "문서에서 정리하는 것", today=date(2026, 10, 12)) == []


def test_generic_dirs_do_not_boost(store):
    _ep(store, "테스트 전략 정리", project="workspace")
    [h] = recall.recall(store, "테스트 전략", cwd="/Users/a/workspace/other", today=date(2026, 10, 12))
    assert "같은 프로젝트" not in h.why


def test_no_match_returns_empty(store):
    _ep(store, "UI 화면 설계")
    assert recall.recall(store, "zzz qqq", today=date(2026, 10, 12)) == []
    assert recall.render([]) == ""


def test_scope_for_work_paths():
    cfg = config.Config(machine="w", stores={"personal": "p", "work": "w"}, work_paths=("C:\\Work",))
    assert cfg.scope_for("c:/work/acme") == "work"
    assert cfg.scope_for("C:\\Workshop") == "personal"
    assert config.Config(machine="m", stores={"personal": "p"}, work_paths=("/w",)).scope_for("/w/x") == "personal"


def test_revise_keeps_previous_version(store):
    e1, e2 = _ep(store, "a"), _ep(store, "b")
    op = store.add("opinion", {"statement": "구버전 판단", "evidence": [e1.id], "counter_evidence": []}, "구버전 판단")
    p = json.loads(reflect.run(store, FakeLLM({"evidence_updates": [], "new_opinions": [], "new_procedures": [], "observations": [],
                                              "invalidations": [], "revisions": [{"id": op.id, "statement": "신버전 판단", "rules": [], "supports": [e2.id], "reason": "범위 조정"}]})).read_text(encoding="utf-8"))
    assert p["items"][0]["op"] == "revise"
    review.decide(store, p["id"], accept=True)
    after = store.get(op.id)
    assert after.meta["statement"] == "신버전 판단" and after.body.strip() == "신버전 판단"
    assert after.meta["versions"][0]["statement"] == "구버전 판단"
    assert after.meta["evidence"] == [e1.id]  # 표현 수정은 confidence를 바꾸지 않음
    assert after.meta["versions"][0]["revised_with"] == [e2.id]


def test_revise_without_evidence_is_dropped(store):
    _ep(store, "a")
    op = store.add("opinion", {"statement": "s", "evidence": [], "counter_evidence": []}, "s")
    p = json.loads(reflect.run(store, FakeLLM({"evidence_updates": [], "new_opinions": [], "new_procedures": [], "observations": [],
                                              "invalidations": [], "revisions": [{"id": op.id, "statement": "x", "rules": [], "supports": [], "reason": "근거 없음"}]})).read_text(encoding="utf-8"))
    assert p["items"] == []


def test_vcs_commit_and_history(tmp_path):
    root = tmp_path / "s"
    s = Store(root, "mac")
    s.init()
    assert vcs.commit(root, "x") is None  # git 저장소 아니면 무시
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    op = s.add("opinion", {"statement": "v1"}, "v1")
    assert vcs.commit(root, "add v1")
    assert vcs.commit(root, "no change") is None
    op.body = "v2"
    s.save(op)
    vcs.commit(root, "revise v2")
    log = vcs.history(root, op.path.relative_to(root).as_posix())
    assert "revise v2" in log and "add v1" in log and "+v2" in log
    assert "원격 저장소 없음" in vcs.sync(root)
    # events/ 원본 로그는 커밋 대상 아님
    (root / "events" / "mac").mkdir(parents=True, exist_ok=True)
    (root / "events" / "mac" / "x.jsonl").write_text("{}\n", encoding="utf-8")
    assert vcs.commit(root, "events only") is None


def test_commit_without_user_name_uses_fallback(tmp_path, monkeypatch):
    root = tmp_path / "s"
    s = Store(root, "mac")
    s.init()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    # 전역 설정 영향 차단: 빈 HOME/XDG
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    s.add("opinion", {"statement": "v1"}, "v1")
    assert vcs.commit(root, "no identity")
    author = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%an"], capture_output=True, text=True).stdout.strip()
    assert author == "amem"
