import json
from pathlib import Path

import pytest

from amem.store import Store


class FakeLLM:
    """정해진 응답을 돌려주고 받은 프롬프트를 기록."""

    def __init__(self, *responses: dict):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def json(self, prompt: str, schema: dict) -> dict:
        self.prompts.append(prompt)
        return self.responses.pop(0)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "store", "mac")
    s.init()
    return s


def write_events(store: Store, name: str, events: list[dict], machine: str | None = None) -> Path:
    d = store.root / "events" / (machine or store.machine)
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    return p


def ev(kind: str, name: str, target=None, ok=None, ts="2026-10-12T10:00:00+09:00") -> dict:
    d = {"ts": ts, "kind": kind, "name": name}
    if target is not None:
        d["target"] = target
    if ok is not None:
        d["ok"] = ok
    return d
