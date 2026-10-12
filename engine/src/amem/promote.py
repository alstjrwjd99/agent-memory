"""events → episode 승격. 신호 없는 세션은 LLM 호출 없이 처리 완료로 표시."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import schema, signals, transcript
from .events import SessionLog, sessions
from .llm import Backend
from .store import Store

PROMPT = """너는 에이전트 기억 시스템의 episode 추출기다.
아래는 한 작업 세션의 이벤트 요약, 규칙 기반으로 감지된 신호, 대화 발췌다.

episode로 남길 가치가 있는 경험만 추출하라. 기준:
- 사용자가 에이전트 판단을 교정함
- 실패 → 재시도 → 성공
- 새로운 의사결정이 생김
- 반복적으로 등장한 문제
- 기존 방식과 충돌하거나 새로운 작업 방식을 발견
- 결과가 명확하게 좋거나 나빴음
단순 진행 기록, 일상적 조회, 사소한 수정은 제외한다. 남길 게 없으면 episodes를 빈 배열로.
아래 "이미 추출된 episode"와 같은 내용은 다시 만들지 마라 (세션이 이어져 새 부분만 처리하는 경우).

각 episode 필드:
- title: 짧은 제목
- event: 무슨 상황이었나 (1~2문장)
- action: 무엇을 했나/바꿨나
- result: 결과가 어땠나
- project: 프로젝트 이름 (모르면 "unknown")
- signals: 근거가 된 신호 종류 (correction, retry_success, repeated_failure, repeated_sequence, interrupted, decision, outcome 중)
- tags: 상황 태그 1~3개 (예: UI작업, 배포운영, DB작업)

비밀값, 토큰, 고객 원문 데이터는 절대 옮겨 적지 말고 일반화해서 써라. 한국어로.

## 이벤트 요약
{summary}

## 감지된 신호
{signals}

## 이미 추출된 episode
{existing}

## 대화 발췌
{excerpt}
"""


@dataclass
class PromoteResult:
    scanned: int = 0
    skipped_no_signal: int = 0
    llm_calls: int = 0
    episodes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def pending(store: Store) -> list[tuple[SessionLog, int]]:
    """처리 안 된 (세션, 시작 인덱스). 세션 파일이 이어서 자랐으면 새 부분만."""
    done = store.load_state("processed")
    out = []
    for log in sessions(store.root, store.machine):
        start = int(done.get(log.key, 0))
        # 파일이 줄어들었으면(덮어쓰기 등) 처음부터 다시
        if start > len(log.events):
            start = 0
        if len(log.events) > start:
            out.append((log, start))
    return out


def run(store: Store, llm: Backend | None, claude_home: Path, dry_run: bool = False, include_quiet: bool = False) -> PromoteResult:
    res = PromoteResult()
    done = store.load_state("processed")
    try:
        _run(store, llm, claude_home, dry_run, include_quiet, res, done)
    finally:
        # 중간에 예외가 나도 이미 처리한 세션은 기록 (다음 실행에서 중복 episode 방지)
        if not dry_run:
            store.save_state("processed", done)
    return res


def _run(store: Store, llm: Backend | None, claude_home: Path, dry_run: bool, include_quiet: bool, res: PromoteResult, done: dict) -> None:
    for log, start in pending(store):
        res.scanned += 1
        events = log.events[start:]
        sigs = signals.detect(events)
        if not sigs and not include_quiet:
            res.skipped_no_signal += 1
            if not dry_run:
                done[log.key] = len(log.events)
            continue
        if dry_run or llm is None:
            res.episodes.append(f"(dry-run) {log.key}: " + ", ".join(s.kind for s in sigs))
            continue
        tpath = transcript.find(claude_home, log.session)
        existing = [e.meta.get("title") for e in store.items("experience") if (e.meta.get("source") or {}).get("session") == log.session]
        prompt = PROMPT.format(
            existing="\n".join(f"- {t}" for t in existing) or "- (없음)",
            summary=signals.summarize(events),
            signals="\n".join(f"- {s.kind}: {s.detail}" for s in sigs) or "- (없음)",
            excerpt=transcript.excerpt(tpath) if tpath else "(transcript 없음: 다른 PC 세션이거나 삭제됨)",
        )
        try:
            out = llm.json(prompt, schema.EPISODES)
            res.llm_calls += 1
            eps = [ep for ep in out.get("episodes", []) if all(k in ep for k in ("title", "event", "action", "result"))]
        except Exception as e:  # 한 세션 실패가 전체를 막지 않게
            res.errors.append(f"{log.key}: {e}")
            continue
        for ep in eps:
            item = store.add(
                "experience",
                {
                    "title": ep["title"],
                    "event": ep["event"],
                    "action": ep["action"],
                    "result": ep["result"],
                    "project": ep.get("project") or "unknown",
                    "signals": ep.get("signals") or [],
                    "tags": [f"상황/{t}" for t in ep.get("tags") or []],
                    "source": {"machine": log.machine, "session": log.session, "date": log.date},
                    "time": log.date,
                },
                f"# {ep['title']}\n\n- 상황: {ep['event']}\n- 행동: {ep['action']}\n- 결과: {ep['result']}",
            )
            res.episodes.append(item.id)
        done[log.key] = len(log.events)
