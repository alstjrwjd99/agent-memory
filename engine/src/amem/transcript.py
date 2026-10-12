"""Claude Code 로컬 transcript에서 대화 발췌 (같은 PC에서만 읽음, store에는 원문 저장 X)."""
from __future__ import annotations

import json
from pathlib import Path

PER_MESSAGE = 600
TOTAL = 16000


def find(claude_home: Path, session_prefix: str) -> Path | None:
    projects = claude_home / "projects"
    if not projects.exists() or not session_prefix:
        return None
    hits = sorted(projects.glob(f"*/{session_prefix}*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""


def excerpt(path: Path) -> str:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if d.get("type") not in ("user", "assistant") or d.get("isMeta"):
            continue
        msg = d.get("message") or {}
        text = _text(msg.get("content")).strip()
        if not text or text.startswith("<"):
            # 시스템 주입/명령 출력 같은 태그 블록은 제외
            continue
        role = "U" if d["type"] == "user" else "A"
        lines.append(f"[{role}] {text[:PER_MESSAGE]}")
    joined = "\n".join(lines)
    if len(joined) <= TOTAL:
        return joined
    # 앞부분(목적)과 뒷부분(결과)을 남기고 가운데를 자른다
    half = TOTAL // 2
    return joined[:half] + "\n…(중략)…\n" + joined[-half:]
