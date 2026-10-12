"""memory-events mod가 남긴 events/<machine>/<날짜>_<세션8>.jsonl 읽기."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Event:
    ts: str
    kind: str  # tool | correction | turn
    name: str
    target: str | None = None
    ok: bool | None = None


@dataclass
class SessionLog:
    path: Path
    machine: str
    date: str
    session: str  # 세션 id 앞 8자
    events: list[Event]

    @property
    def key(self) -> str:
        return f"{self.machine}/{self.path.name}"


def read_events(path: Path) -> list[Event]:
    out: list[Event] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            if not isinstance(d, dict):
                continue
            out.append(Event(ts=str(d["ts"]), kind=str(d["kind"]), name=str(d["name"]), target=d.get("target"), ok=d.get("ok")))
        except (json.JSONDecodeError, KeyError):
            # 깨진 줄은 건너뛴다 (세션 도중 강제 종료 등)
            continue
    return out


def sessions(store_root: Path, machine: str) -> list[SessionLog]:
    d = store_root / "events" / machine
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.jsonl")):
        stem = f.stem
        day, _, sid = stem.partition("_")
        out.append(SessionLog(path=f, machine=machine, date=day, session=sid, events=read_events(f)))
    return out
