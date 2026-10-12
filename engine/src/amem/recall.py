"""recall: 지금 프롬프트와 관련된 기억을 골라 꺼낸다 (LLM 없음, Hindsight TEMPR의 경량판).

점수 = 키워드 유사도(BM25, 한국어는 글자 2-gram) × 프로젝트 가중 × 확신도/최신성
     + 링크 확장(걸린 episode를 근거로 한 판단, 판단의 근거 episode)
검색기는 Retriever 프로토콜로 분리해 나중에 임베딩/실제 Hindsight로 교체 가능.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import PurePath
from typing import Protocol

from . import confidence
from .store import Item, Store

RECALL_KINDS = ("opinion", "procedure", "observation", "experience", "world")
# 판단/절차가 실제 행동을 바꾸므로 우선
KIND_WEIGHT = {"procedure": 1.3, "opinion": 1.2, "observation": 1.0, "world": 1.0, "experience": 0.8}
PROJECT_BOOST = 1.6
HALF_LIFE_DAYS = 45
MIN_SCORE = 0.8
_WORD = re.compile(r"[a-z0-9]+|[가-힣]+")
STOP = {"the", "and", "for", "this", "that", "with", "해줘", "해봐", "그리고", "이거", "그거", "뭐야", "있어", "하는"}
# 조사/어미에서 나오는 흔한 2-gram: 거의 모든 한국어 문서에 걸려 잡음이 됨
STOP_BIGRAMS = {"에서", "하는", "니다", "습니", "으로", "에게", "했다", "한다", "하고", "해서", "있다", "었다", "였다", "지만",
                "는데", "을까", "할까", "어요", "해요", "아요", "세요", "이다", "하게", "되는", "된다", "까지", "부터", "처럼"}
# 프로젝트 매칭에서 제외할 일반 폴더명
GENERIC_DIRS = {"users", "home", "workspace", "work", "src", "projects", "documents", "desktop", "repos", "code", "dev", "tmp"}
MIN_MATCHED_TOKENS = 2


def tokens(text: str) -> list[str]:
    """영문/숫자는 단어, 한국어는 단어 + 글자 2-gram (조사 붙은 형태도 매칭되게)."""
    out: list[str] = []
    for w in _WORD.findall(text.lower()):
        if w in STOP:
            continue
        if re.match(r"[가-힣]", w):
            if len(w) > 1:
                out.extend(g for g in (w[i : i + 2] for i in range(len(w) - 1)) if g not in STOP_BIGRAMS)
        elif len(w) >= 2:
            out.append(w)
    return out


def text_of(i: Item) -> str:
    m = i.meta
    parts = [str(m.get(k) or "") for k in ("statement", "trigger", "subject", "title", "event", "action", "result", "project")]
    parts += [str(r) for r in m.get("rules") or []]
    parts += [str(t) for t in m.get("tags") or []]
    parts.append(i.body)
    return " ".join(parts)


@dataclass
class Hit:
    item: Item
    score: float
    why: list[str] = field(default_factory=list)


class Retriever(Protocol):
    def search(self, query: str, items: list[Item]) -> dict[str, float]: ...


class BM25:
    def __init__(self, k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b

    def search(self, query: str, items: list[Item]) -> dict[str, float]:
        q = set(tokens(query))
        if not q or not items:
            return {}
        docs = {i.id: Counter(tokens(text_of(i))) for i in items}
        n = len(docs)
        avg = sum(sum(d.values()) for d in docs.values()) / n or 1
        df = Counter(t for d in docs.values() for t in set(d) if t in q)
        out: dict[str, float] = {}
        need = min(MIN_MATCHED_TOKENS, len(q))
        for doc_id, tf in docs.items():
            # 우연히 한 토큰만 겹친 문서는 제외 (짧은 질의는 그 길이까지만 요구)
            if sum(1 for t in q if tf[t]) < need:
                continue
            dl = sum(tf.values()) or 1
            s = 0.0
            for t in q:
                if tf[t]:
                    idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    s += idf * tf[t] * (self.k1 + 1) / (tf[t] + self.k1 * (1 - self.b + self.b * dl / avg))
            if s > 0:
                out[doc_id] = s
        return out


def _project_names(i: Item, by_id: dict[str, Item]) -> set[str]:
    """기억이 속한 프로젝트: episode는 자기 project, 판단은 근거 episode들의 project."""
    names = {str(i.meta.get("project") or "")}
    if i.kind == "observation":
        names.add(str(i.meta.get("subject") or ""))
    for ep in i.meta.get("evidence") or []:
        if ep in by_id:
            names.add(str(by_id[ep].meta.get("project") or ""))
    return {n.lower() for n in names if n and n != "unknown"}


def _age_days(i: Item, today: date) -> float:
    raw = str(i.meta.get("time") or i.meta.get("updated_at") or i.meta.get("created_at") or "")[:10]
    try:
        return max(0, (today - datetime.fromisoformat(raw).date()).days)
    except ValueError:
        return 0


def recall(store: Store, query: str, cwd: str = "", k: int = 5, retriever: Retriever | None = None, today: date | None = None) -> list[Hit]:
    today = today or date.today()
    items = [i for i in store.items() if i.kind in RECALL_KINDS and i.meta.get("status") == "active"]
    by_id = {i.id: i for i in items}
    raw = (retriever or BM25()).search(query, items)
    # 작업 폴더 경로의 이름들 (맥/윈도우 모두): 프로젝트 매칭용
    cwd_parts = {p.lower() for p in PurePath(cwd.replace("\\", "/")).parts if len(p) > 2} - GENERIC_DIRS if cwd else set()

    hits: dict[str, Hit] = {}
    for item_id, s in raw.items():
        i = by_id[item_id]
        why = [f"키워드 {s:.1f}"]
        score = s * KIND_WEIGHT[i.kind]
        if cwd_parts & _project_names(i, by_id):
            score *= PROJECT_BOOST
            why.append("같은 프로젝트")
        if i.kind in ("opinion", "procedure"):
            c = confidence.of(i.meta)
            score *= 0.5 + c
            why.append(f"확신도 {c:.2f}")
        else:
            score *= 0.5 ** (_age_days(i, today) / HALF_LIFE_DAYS) * 0.5 + 0.5
        hits[item_id] = Hit(i, score, why)

    # 링크 확장: 걸린 episode를 근거로 삼는 판단도 끌어온다 (그래프 한 단계)
    for h in list(hits.values()):
        if h.item.kind != "experience":
            continue
        for j in items:
            if j.kind in ("opinion", "procedure", "observation") and h.item.id in (j.meta.get("evidence") or []):
                linked = h.score * 0.7 * (0.5 + confidence.of(j.meta) if j.kind != "observation" else 1)
                if j.id not in hits or hits[j.id].score < linked:
                    hits[j.id] = Hit(j, linked, [f"근거 {h.item.id} 경유"])

    ranked = sorted((h for h in hits.values() if h.score >= MIN_SCORE), key=lambda h: h.score, reverse=True)
    return ranked[:k]


def render(hits: list[Hit]) -> str:
    """프롬프트 옆에 붙일 컨텍스트 블록."""
    if not hits:
        return ""
    lines = ["[agent-memory recall] 지금 요청과 관련된 과거 기억이다. 참고만 하고, 현재 상황과 다르면 무시하라."]
    for h in hits:
        m = h.item.meta
        if h.item.kind == "opinion":
            lines.append(f"- 판단(conf {confidence.of(m):.2f}): {m.get('statement')}")
        elif h.item.kind == "procedure":
            lines.append(f"- 절차: {m.get('trigger')} → {' → '.join(m.get('rules') or [])}")
        elif h.item.kind == "observation":
            lines.append(f"- 관찰[{m.get('subject')}]: {h.item.body.strip()[:200]}")
        elif h.item.kind == "experience":
            lines.append(f"- 경험({m.get('time')}): {m.get('title')} / 결과: {m.get('result')}")
        else:
            lines.append(f"- 사실: {h.item.body.strip()[:200]}")
    return "\n".join(lines)
