"""규칙 기반 신호 감지 (LLM 비용 없음). 신호가 있는 세션만 episode 후보로 올린다."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .events import Event

# 읽기 전용 도구만으로 된 반복은 "단순 반복"이라 제외
READ_ONLY = {"Read", "Grep", "Glob", "LS", "WebSearch", "WebFetch", "ToolSearch", "TodoWrite"}
RETRY_WINDOW = 10
SEQ_LEN = 3
SEQ_MIN = 3
FAIL_MIN = 3


@dataclass(frozen=True)
class Signal:
    kind: str  # correction | retry_success | repeated_failure | repeated_sequence | interrupted
    detail: str
    at: int  # 이벤트 인덱스


def detect(events: list[Event]) -> list[Signal]:
    out: list[Signal] = []
    tools = [(i, e) for i, e in enumerate(events) if e.kind == "tool"]

    # 1) 사용자 교정
    for i, e in enumerate(events):
        if e.kind == "correction":
            out.append(Signal("correction", f"사용자 교정 신호 '{e.name}'", i))
        if e.kind == "turn" and e.name == "aborted":
            out.append(Signal("interrupted", "사용자가 턴을 중단함", i))

    # 2) 실패 → 재시도 → 성공 (같은 도구, 대상이 있으면 대상도 같아야)
    for pos, (i, e) in enumerate(tools):
        if e.ok is not False:
            continue
        for j, later in tools[pos + 1 : pos + 1 + RETRY_WINDOW]:
            if later.name == e.name and later.ok and (e.target is None or later.target == e.target):
                out.append(Signal("retry_success", f"{e.name} {e.target or ''} 실패 후 재시도 성공".strip(), j))
                break

    # 3) 같은 도구 반복 실패
    fails = Counter(e.name for _, e in tools if e.ok is False)
    for name, n in fails.items():
        if n >= FAIL_MIN:
            out.append(Signal("repeated_failure", f"{name} {n}회 실패", -1))

    # 4) 반복되는 도구 시퀀스 (순서와 판단이 있는 절차 후보)
    names = [e.name for _, e in tools]
    grams = Counter(tuple(names[k : k + SEQ_LEN]) for k in range(len(names) - SEQ_LEN + 1))
    for gram, n in grams.items():
        if n >= SEQ_MIN and not set(gram) <= READ_ONLY and len(set(gram)) > 1:
            out.append(Signal("repeated_sequence", f"{' → '.join(gram)} {n}회 반복", -1))

    return out


def summarize(events: list[Event]) -> str:
    """LLM에 줄 이벤트 요약 (원문 없음)."""
    turns = sum(1 for e in events if e.kind == "turn")
    tools = Counter(e.name for e in events if e.kind == "tool")
    fails = sum(1 for e in events if e.kind == "tool" and e.ok is False)
    top = ", ".join(f"{k}×{v}" for k, v in tools.most_common(8))
    return f"턴 {turns}회, 도구 호출 {sum(tools.values())}회(실패 {fails}): {top}"
