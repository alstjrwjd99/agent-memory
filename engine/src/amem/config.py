"""설정 로드: ~/.config/agent-memory/config.yaml (맥/윈도우 공통 경로), AMEM_CONFIG로 덮어쓰기."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_MODEL = "claude-opus-5-5"


@dataclass(frozen=True)
class Config:
    machine: str
    stores: dict[str, Path]
    model: str = DEFAULT_MODEL
    # claude-cli: Claude Code 로그인 재사용 / sdk: anthropic SDK (API 키 또는 ant 로그인 필요)
    backend: str = "claude-cli"
    export_threshold: float = 0.7
    # Claude Code 홈 (export 대상 memory 폴더 계산용)
    claude_home: Path = field(default_factory=lambda: Path.home() / ".claude")

    def store(self, scope: str) -> Path:
        if scope not in self.stores:
            raise SystemExit(f"store '{scope}' 미설정: config.yaml stores 확인 ({config_path()})")
        return self.stores[scope]


def config_path() -> Path:
    env = os.environ.get("AMEM_CONFIG")
    return Path(env) if env else Path.home() / ".config" / "agent-memory" / "config.yaml"


def load(path: Path | None = None) -> Config:
    p = path or config_path()
    if not p.exists():
        raise SystemExit(f"설정 파일 없음: {p}\n`amem init --machine <이름> --personal <경로>`로 생성하세요")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    stores = {k: Path(v).expanduser() for k, v in (raw.get("stores") or {}).items() if v}
    return Config(
        machine=str(raw.get("machine") or "unknown"),
        stores=stores,
        model=str(raw.get("model") or DEFAULT_MODEL),
        backend=str(raw.get("backend") or "claude-cli"),
        export_threshold=float(raw.get("export_threshold") or 0.7),
        claude_home=Path(raw["claude_home"]).expanduser() if raw.get("claude_home") else Path.home() / ".claude",
    )


def write_default(path: Path, machine: str, personal: str | None, work: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "machine": machine,
        "stores": {k: v for k, v in {"personal": personal, "work": work}.items() if v},
        "model": DEFAULT_MODEL,
        "backend": "claude-cli",
        "export_threshold": 0.7,
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
