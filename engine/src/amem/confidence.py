"""confidence 계산: LLM이 숫자를 만들지 않고 근거 개수로 계산 (Laplace 보정)."""
from __future__ import annotations


def confidence(support: int, counter: int) -> float:
    return (support + 1) / (support + counter + 2)


def of(item_meta: dict) -> float:
    return confidence(len(item_meta.get("evidence") or []), len(item_meta.get("counter_evidence") or []))


def is_conflicted(item_meta: dict) -> bool:
    """반례가 지지 근거 이상이면 충돌 상태로 본다."""
    counter = len(item_meta.get("counter_evidence") or [])
    return counter > 0 and counter >= len(item_meta.get("evidence") or [])
