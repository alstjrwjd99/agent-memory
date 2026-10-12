"""git 어댑터: prompt 커밋 ~ 다음 prompt 커밋을 작업 단위로 묶어 episode 후보로 만든다.

prompt 커밋(사용자가 AI에게 준 지시) = 의도, 이어진 커밋 = 행동, 커밋 본문/다음 prompt의 "→ 결과" = 결과.
코드 diff는 읽지 않는다 (커밋 메시지 + 변경 파일 목록만).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import schema
from .llm import Backend
from .store import Store

PROMPT_RE = re.compile(r"^\s*prompt\s*[:：]", re.I)
FIX_RE = re.compile(r"^(fix|revert|hotfix)\b|되돌|롤백|고친다|고침|버그|떨어지던|안 되던|깨지던", re.I)
FEEDBACK_RE = re.compile(r"피드백|지적|요청 반영|리뷰 반영|codex", re.I)
STILL_RE = re.compile(r"여전히|아직도|다시|또 |안 ?됨|안 ?돼|틀렸|잘못")
TRAILER_RE = re.compile(r"^(Co-Authored-By|Signed-off-by):.*$", re.I | re.M)
BATCH = 8


@dataclass
class Commit:
    sha: str
    date: str
    subject: str
    body: str
    files: list[str]

    @property
    def is_prompt(self) -> bool:
        return bool(PROMPT_RE.match(self.subject))


@dataclass
class Unit:
    """작업 단위: prompt 커밋 1개 + 이어진 작업 커밋들."""
    prompt: Commit
    commits: list[Commit] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.prompt.sha[:12]

    @property
    def files(self) -> set[str]:
        return {f for c in self.commits for f in c.files}


def read_log(repo: Path, since: str | None = None, until: str | None = None) -> list[Commit]:
    args = ["git", "-C", str(repo), "log", "--no-merges", "--reverse", "--name-only", "--date=short",
            "--format=%x1e%H%x1f%ad%x1f%s%x1f%b%x1d"]
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout
    commits: list[Commit] = []
    for rec in out.split("\x1e"):
        if "\x1d" not in rec:
            continue
        head, _, files = rec.partition("\x1d")
        sha, date, subject, body = (head.split("\x1f") + ["", "", "", ""])[:4]
        body = TRAILER_RE.sub("", body).strip()
        commits.append(Commit(sha, date, subject.strip(), body, [f for f in files.strip().splitlines() if f.strip()]))
    return commits


def units(commits: list[Commit]) -> list[Unit]:
    """prompt 커밋 앞의 커밋은 버린다 (의도를 모르는 행동)."""
    out: list[Unit] = []
    for c in commits:
        if c.is_prompt:
            out.append(Unit(c))
        elif out:
            out[-1].commits.append(c)
    _signals(out)
    return out


def _signals(us: list[Unit]) -> None:
    for i, u in enumerate(us):
        texts = [u.prompt.subject + " " + u.prompt.body] + [c.subject + " " + c.body for c in u.commits]
        if STILL_RE.search(texts[0]):
            u.signals.append("correction")  # 지시 자체가 "여전히 안 됨" 류 → 이전 시도가 틀렸음
        if any(FEEDBACK_RE.search(t) for t in texts):
            u.signals.append("external_feedback")
        if any(FIX_RE.search(c.subject) for c in u.commits):
            u.signals.append("fix_in_unit")
        if "→" in u.prompt.subject or "->" in u.prompt.subject:
            u.signals.append("outcome_recorded")
        if len(u.commits) >= 5:
            u.signals.append("large_unit")
        # 바로 다음 단위가 같은 파일을 다시 고치면 재작업 (실패 → 재시도)
        if i + 1 < len(us) and u.files & us[i + 1].files:
            nxt = us[i + 1]
            if STILL_RE.search(nxt.prompt.subject) or any(FIX_RE.search(c.subject) for c in nxt.commits):
                u.signals.append("reworked_next")


def fmt_unit(n: int, u: Unit) -> str:
    lines = [f"### 단위 {n} ({u.prompt.date}) 신호: {', '.join(u.signals) or '-'}", f"지시: {u.prompt.subject}"]
    if u.prompt.body:
        lines.append(f"  {u.prompt.body[:300]}")
    for c in u.commits[:12]:
        lines.append(f"- {c.subject}")
        if c.body:
            lines.append("  " + c.body[:400].replace("\n", "\n  "))
    files = sorted(u.files)
    if files:
        lines.append(f"변경 파일({len(files)}): {', '.join(files[:10])}" + (" …" if len(files) > 10 else ""))
    return "\n".join(lines)


PROMPT = """너는 에이전트 기억 시스템의 episode 추출기다. 아래는 한 저장소({repo})의 작업 단위들이다.
각 단위 = 사용자가 AI 코딩 에이전트에게 준 지시(prompt 커밋) + 이어진 실제 커밋들(제목과 본문).

경험(episode)으로 남길 가치가 있는 것만 추출하라. 기준:
- 사용자나 고객이 이전 결과를 교정함 ("여전히", "피드백 반영" 등)
- 시도 → 문제 발견 → 재작업
- 도메인 규칙이나 설계 판단이 드러남 (왜 그렇게 고쳤는지가 본문에 있음)
- 결과가 명확히 좋거나 나빴음
단순 UI 미세조정, 문구 수정, 반복되는 사소한 작업은 제외. 여러 단위가 하나의 경험이면 합쳐라.

각 episode 필드:
- title: 짧은 제목
- event: 상황 (무엇이 문제였나/무엇을 하려 했나)
- action: 실제로 한 것 (판단 근거 포함)
- result: 결과
- project: "{project}"
- signals: correction, external_feedback, retry_success, decision, outcome 중 해당
- tags: 상황 태그 1~3개
- units: 근거가 된 단위 번호들

배운 점이 드러나도록 쓰되, 커밋에 없는 내용은 지어내지 마라. 비밀값은 옮기지 마라. 한국어로.

{units}
"""


@dataclass
class IngestResult:
    units_total: int = 0
    units_with_signal: int = 0
    skipped_done: int = 0
    llm_calls: int = 0
    episodes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def run(store: Store, llm: Backend | None, repo: Path, project: str, since: str | None = None, until: str | None = None,
        dry_run: bool = False, batch: int = BATCH) -> IngestResult:
    res = IngestResult()
    state = store.load_state("ingest-git")
    done: set[str] = set(state.get(project, []))
    all_units = units(read_log(repo, since, until))
    res.units_total = len(all_units)
    todo = []
    for u in all_units:
        if u.key in done:
            res.skipped_done += 1
        elif u.signals:
            todo.append(u)
        else:
            done.add(u.key)  # 신호 없는 단위는 LLM 없이 처리 완료
    res.units_with_signal = len(todo)
    if dry_run or llm is None:
        for u in todo:
            res.episodes.append(f"(dry-run) {u.prompt.date} [{', '.join(u.signals)}] {u.prompt.subject[:60]}")
        return res
    try:
        for start in range(0, len(todo), batch):
            chunk = todo[start : start + batch]
            prompt = PROMPT.format(repo=repo.name, project=project, units="\n\n".join(fmt_unit(i + 1, u) for i, u in enumerate(chunk)))
            try:
                out = llm.json(prompt, schema.GIT_EPISODES)
                res.llm_calls += 1
            except Exception as e:
                res.errors.append(f"batch {start // batch + 1}: {e}")
                continue
            for ep in out.get("episodes", []):
                if not all(k in ep for k in ("title", "event", "action", "result")):
                    continue
                src_units = [chunk[n - 1] for n in ep.get("units", []) if isinstance(n, int) and 1 <= n <= len(chunk)]
                item = store.add(
                    "experience",
                    {
                        "title": ep["title"], "event": ep["event"], "action": ep["action"], "result": ep["result"],
                        "project": project, "signals": ep.get("signals") or [],
                        "tags": [f"상황/{t}" for t in ep.get("tags") or []],
                        "source": {"type": "git", "repo": repo.name,
                                   "commits": [c.sha[:12] for u in src_units for c in [u.prompt, *u.commits]]},
                        "time": (src_units[0].prompt.date if src_units else chunk[0].prompt.date),
                    },
                    f"# {ep['title']}\n\n- 상황: {ep['event']}\n- 행동: {ep['action']}\n- 결과: {ep['result']}",
                )
                res.episodes.append(item.id)
            done.update(u.key for u in chunk)
    finally:
        state[project] = sorted(done)
        store.save_state("ingest-git", state)
    return res
