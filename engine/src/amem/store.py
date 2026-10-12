"""store: kind별 폴더 + 마크다운(YAML frontmatter) 파일. 삭제하지 않고 status로 수명 관리."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

# kind → (폴더, id 접두어)
KINDS: dict[str, tuple[str, str]] = {
    "experience": ("episodes", "ep"),
    "world": ("world", "wf"),
    "observation": ("observations", "ob"),
    "opinion": ("opinions", "op"),
    "procedure": ("procedures", "pr"),
}
STATUSES = ("active", "superseded", "invalidated", "low_confidence")
_FM = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", re.S)


@dataclass
class Item:
    meta: dict
    body: str
    path: Path

    @property
    def id(self) -> str:
        return str(self.meta["id"])

    @property
    def kind(self) -> str:
        return str(self.meta["type"])


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> str:
    return date.today().isoformat()


def parse(text: str) -> tuple[dict, str]:
    m = _FM.match(text)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def dump(meta: dict, body: str) -> str:
    fm = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm}\n---\n{body.strip()}\n"


class Store:
    def __init__(self, root: Path, machine: str):
        self.root = Path(root)
        self.machine = machine

    # ---- 경로 ----
    def dir(self, kind: str) -> Path:
        return self.root / KINDS[kind][0]

    @property
    def state_dir(self) -> Path:
        return self.root / ".amem"

    def init(self) -> None:
        for folder, _ in KINDS.values():
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        for extra in ("events", "proposals", ".amem"):
            (self.root / extra).mkdir(parents=True, exist_ok=True)

    # ---- 읽기 ----
    def items(self, kind: str | None = None) -> list[Item]:
        kinds = [kind] if kind else list(KINDS)
        out: list[Item] = []
        for k in kinds:
            d = self.dir(k)
            if not d.exists():
                continue
            for f in sorted(d.glob("*.md")):
                meta, body = parse(f.read_text(encoding="utf-8"))
                if meta.get("id"):
                    out.append(Item(meta, body, f))
        return out

    def get(self, item_id: str) -> Item | None:
        prefix = item_id.split("_", 1)[0]
        for kind, (_, p) in KINDS.items():
            if p == prefix:
                f = self.dir(kind) / f"{item_id}.md"
                if f.exists():
                    meta, body = parse(f.read_text(encoding="utf-8"))
                    return Item(meta, body, f)
        return None

    # ---- 쓰기 ----
    def new_id(self, kind: str, on: str | None = None) -> str:
        # 파일명에 PC 이름을 넣어 두 PC가 동시에 만들어도 충돌하지 않게
        prefix = KINDS[kind][1]
        stamp = (on or today()).replace("-", "")
        base = f"{prefix}_{stamp}_{self.machine}_"
        d = self.dir(kind)
        n = len(list(d.glob(f"{base}*.md"))) + 1 if d.exists() else 1
        while (d / f"{base}{n:03d}.md").exists():
            n += 1
        return f"{base}{n:03d}"

    def add(self, kind: str, meta: dict, body: str) -> Item:
        self.dir(kind).mkdir(parents=True, exist_ok=True)
        item_id = self.new_id(kind)
        ts = now_iso()
        full = {"id": item_id, "type": kind, **meta}
        full.setdefault("status", "active")
        full.setdefault("created_at", ts)
        full["updated_at"] = ts
        path = self.dir(kind) / f"{item_id}.md"
        path.write_text(dump(full, body), encoding="utf-8", newline="\n")
        return Item(full, body, path)

    def save(self, item: Item) -> None:
        item.meta["updated_at"] = now_iso()
        item.path.write_text(dump(item.meta, item.body), encoding="utf-8", newline="\n")

    # ---- 상태 파일 (PC별로 분리해 sync 충돌 방지) ----
    def _state_file(self, name: str) -> Path:
        return self.state_dir / f"{name}-{self.machine}.json"

    def load_state(self, name: str) -> dict:
        f = self._state_file(name)
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    def save_state(self, name: str, data: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._state_file(name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
