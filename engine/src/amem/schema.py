"""LLM 구조화 출력용 JSON Schema (strict: 모든 필드 required, 추가 필드 금지)."""
from __future__ import annotations

STR = {"type": "string"}
STRS = {"type": "array", "items": STR}


def obj(**props) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def arr(item: dict) -> dict:
    return {"type": "array", "items": item}


EPISODES = obj(
    episodes=arr(obj(title=STR, event=STR, action=STR, result=STR, project=STR, signals=STRS, tags=STRS)),
)

REFLECTION = obj(
    evidence_updates=arr(obj(id=STR, supports=STRS, contradicts=STRS, reason=STR)),
    new_opinions=arr(obj(statement=STR, supports=STRS, contradicts=STRS, reason=STR)),
    new_procedures=arr(obj(trigger=STR, rules=STRS, derived_from=STRS, reason=STR)),
    observations=arr(obj(subject=STR, summary=STR, sources=STRS)),
    invalidations=arr(obj(id=STR, reason=STR)),
    # 기존 판단/절차의 문장 자체를 고침 (opinion은 statement, procedure는 rules 사용, 안 쓰는 쪽은 빈 값)
    revisions=arr(obj(id=STR, statement=STR, rules=STRS, supports=STRS, reason=STR)),
)
