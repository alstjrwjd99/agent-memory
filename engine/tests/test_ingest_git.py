import subprocess
from pathlib import Path

from amem import ingest_git

from conftest import FakeLLM


def _repo(tmp_path: Path, commits: list[tuple[str, str, dict[str, str]]]) -> Path:
    """(제목, 본문, {파일: 내용}) 순서대로 커밋한 임시 저장소."""
    r = tmp_path / "repo"
    r.mkdir()
    g = lambda *a: subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)  # noqa: E731
    g("init", "-q")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    for subject, body, files in commits:
        for name, content in files.items():
            (r / name).write_text(content, encoding="utf-8")
        g("add", "-A")
        g("commit", "-q", "--allow-empty", "-m", subject + ("\n\n" + body if body else ""))
    return r


def test_units_group_prompt_and_following_commits(tmp_path):
    repo = _repo(tmp_path, [
        ("초기 셋업", "", {"a.py": "1"}),  # prompt 이전 커밋은 버림
        ('prompt: "표 열 폭 줄여줘"', "", {}),
        ("열 폭을 줄인다", "", {"ui.tsx": "1"}),
        ('prompt: "여전히 넓다 → 2줄만 남기기"', "", {}),
        ("헤더를 2줄로 고친다", "원문 단위를 유지해야 해서 줄 수만 줄였다\n\nCo-Authored-By: X <x@y>", {"ui.tsx": "2"}),
        ('prompt: "고객 피드백 반영"', "", {}),
        ("고객 피드백 반영: 단위 환산", "", {"calc.py": "1"}),
    ])
    us = ingest_git.units(ingest_git.read_log(repo))
    assert [u.prompt.subject for u in us] == ['prompt: "표 열 폭 줄여줘"', 'prompt: "여전히 넓다 → 2줄만 남기기"', 'prompt: "고객 피드백 반영"']
    assert [c.subject for c in us[0].commits] == ["열 폭을 줄인다"]
    assert "reworked_next" in us[0].signals  # 다음 단위가 같은 파일을 "여전히"로 다시 고침
    assert {"correction", "outcome_recorded", "fix_in_unit"} <= set(us[1].signals)
    assert "Co-Authored-By" not in us[1].commits[0].body and "원문 단위" in us[1].commits[0].body
    assert "external_feedback" in us[2].signals
    assert "변경 파일(1): ui.tsx" in ingest_git.fmt_unit(1, us[1])


def test_ingest_creates_episodes_with_commit_provenance_and_is_idempotent(store, tmp_path):
    repo = _repo(tmp_path, [
        ('prompt: "그냥 문구 수정"', "", {}),
        ("문구", "", {"x.md": "1"}),  # 신호 없음 → LLM 안 감
        ('prompt: "여전히 13 X 8 이다"', "", {}),
        ("배열을 어댑터 값 우선으로 쓴다", "엔진은 총 배열이 비면 A 타입으로 떨어진다", {"spec.py": "1"}),
    ])
    llm = FakeLLM({"episodes": [{"title": "규격서 배열 값 우선순위", "event": "여전히 13X8", "action": "어댑터 값 우선",
                                 "result": "240 반영", "project": "acme", "signals": ["correction"], "tags": ["설계"], "units": [1, 99]}]})
    r = ingest_git.run(store, llm, repo, "acme")
    assert (r.units_total, r.units_with_signal, r.llm_calls, len(r.episodes)) == (2, 1, 1, 1)
    assert "A 타입으로 떨어진다" in llm.prompts[0] and "그냥 문구 수정" not in llm.prompts[0]
    ep = store.get(r.episodes[0])
    assert ep.meta["source"]["type"] == "git" and len(ep.meta["source"]["commits"]) == 2
    # 다시 돌려도 이미 처리한 단위는 건너뜀
    again = ingest_git.run(store, FakeLLM(), repo, "acme")
    assert again.skipped_done == 2 and again.llm_calls == 0


def test_dry_run_lists_candidates_without_llm(store, tmp_path):
    repo = _repo(tmp_path, [('prompt: "피드백 반영해줘"', "", {}), ("수정", "", {"a": "1"})])
    r = ingest_git.run(store, None, repo, "acme", dry_run=True)
    assert r.units_with_signal == 1 and r.episodes[0].startswith("(dry-run)")
    assert store.load_state("ingest-git") == {}
