"""확신도 높은 opinion/procedure를 Claude Code 기본 메모리 폴더로 내보낸다 (store가 원본, 여기는 view)."""
from __future__ import annotations

import re
from pathlib import Path

from . import confidence
from .store import Store, dump, parse


def memory_dir(claude_home: Path, home: Path | None = None) -> Path:
    # Claude Code 프로젝트 폴더명 규칙: 영숫자 외 문자를 - 로 (C:\Users\a → C--Users-a)
    h = str(home or Path.home())
    return claude_home / "projects" / re.sub(r"[^A-Za-z0-9]", "-", h) / "memory"


def _begin(scope: str) -> str:
    return f"<!-- amem:{scope}:begin -->"


def _end(scope: str) -> str:
    return f"<!-- amem:{scope}:end -->"


def run(store: Store, scope: str, target: Path, threshold: float) -> list[str]:
    target.mkdir(parents=True, exist_ok=True)
    chosen = [
        i for kind in ("opinion", "procedure") for i in store.items(kind)
        if i.meta.get("status") == "active" and confidence.of(i.meta) >= threshold
    ]
    written: set[str] = set()
    lines: list[str] = []
    for i in chosen:
        conf = confidence.of(i.meta)
        name = f"amem_{scope}_{i.id}"
        if i.kind == "opinion":
            title = i.meta["statement"]
            body = f"{i.meta['statement']}\n\n**Why:** 근거 episode {len(i.meta.get('evidence') or [])}개, 반례 {len(i.meta.get('counter_evidence') or [])}개 (conf {conf:.2f})\n**How to apply:** 판단이 필요할 때 참고하되 반례 상황인지 먼저 확인."
        else:
            title = f"{i.meta['trigger']} 절차"
            body = f"트리거: {i.meta['trigger']}\n\n" + "\n".join(f"{k}. {r}" for k, r in enumerate(i.meta.get("rules") or [], 1))
        meta = {"name": name, "description": f"[amem {i.kind} {conf:.2f}] {title}"[:200], "type": "feedback",
                "tags": ["memory/feedback", f"amem/{i.kind}"], "amem_scope": scope, "amem_id": i.id}
        (target / f"{name}.md").write_text(dump(meta, body), encoding="utf-8", newline="\n")
        written.add(f"{name}.md")
        lines.append(f"- [amem {i.kind} {conf:.2f}]({name}.md) — {title[:80]}")
    # 이 scope가 예전에 내보냈지만 이제 기준 미달인 파일 정리 (생성물이라 삭제 OK)
    for f in target.glob("amem_*.md"):
        meta, _ = parse(f.read_text(encoding="utf-8"))
        if meta.get("amem_scope") == scope and f.name not in written:
            f.unlink()
    _update_index(target / "MEMORY.md", scope, lines)
    return lines


def _update_index(index: Path, scope: str, lines: list[str]) -> None:
    text = index.read_text(encoding="utf-8") if index.exists() else "# Memory Index\n"
    block = "\n".join([_begin(scope), *lines, _end(scope)])
    pat = re.compile(re.escape(_begin(scope)) + r".*?" + re.escape(_end(scope)), re.S)
    if pat.search(text):
        text = pat.sub(lambda _m: block, text)
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    index.write_text(text, encoding="utf-8", newline="\n")
