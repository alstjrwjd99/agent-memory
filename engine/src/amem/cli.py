"""amem CLI."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as cfgmod
from . import export, health, llm, promote, reflect, review
from .store import Store


def _store(cfg: cfgmod.Config, scope: str) -> Store:
    s = Store(cfg.store(scope), cfg.machine)
    s.init()
    return s


def main(argv: list[str] | None = None) -> int:
    # 윈도우 콘솔 한글/기호 깨짐 방지
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="amem", description="agent-memory 엔진")
    ap.add_argument("--store", default="personal", help="personal | work (기본 personal)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="설정 파일 생성 + store 폴더 준비")
    p.add_argument("--machine", required=True)
    p.add_argument("--personal")
    p.add_argument("--work")
    p.add_argument("--force", action="store_true")

    sub.add_parser("health", help="Memory Health 출력 + health JSON 갱신")
    p = sub.add_parser("promote", help="events → episode 승격")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--include-quiet", action="store_true", help="신호 없는 세션도 LLM에 보냄")
    p = sub.add_parser("reflect", help="새 episode로 판단 변화 제안 생성")
    p.add_argument("--dry-run", action="store_true", help="프롬프트만 출력")
    sub.add_parser("review", help="승인 대기 제안 목록")
    p = sub.add_parser("apply", help="제안 승인")
    p.add_argument("proposal")
    p.add_argument("--only", help="항목 번호 (예: 1,3)")
    p = sub.add_parser("reject", help="제안 거절")
    p.add_argument("proposal")
    p.add_argument("--only")
    sub.add_parser("export", help="확신도 높은 판단/절차를 Claude Code 메모리로 내보내기")
    sub.add_parser("run", help="promote → reflect → health 한 번에")

    a = ap.parse_args(argv)

    if a.cmd == "init":
        path = cfgmod.config_path()
        if path.exists() and not a.force:
            print(f"이미 있음: {path} (--force로 덮어쓰기)")
        else:
            cfgmod.write_default(path, a.machine, a.personal, a.work)
            print(f"설정 생성: {path}")
        cfg = cfgmod.load(path)
        for scope in cfg.stores:
            s = _store(cfg, scope)
            gi = s.root / ".gitignore"
            if not gi.exists():
                gi.write_text(".amem/health-*.json\n", encoding="utf-8", newline="\n")
            print(f"store 준비: {scope} → {s.root}")
        return 0

    cfg = cfgmod.load()
    store = _store(cfg, a.store)
    only = None
    if getattr(a, "only", None) is not None:
        only = {int(x) for x in a.only.split(",") if x.strip()}
        if not only:
            raise SystemExit("--only에 항목 번호를 넣어주세요 (예: --only 1,3)")

    if a.cmd == "health":
        print(health.render(health.write(store)))
    elif a.cmd in ("promote", "run"):
        backend = None if getattr(a, "dry_run", False) else llm.make(cfg.backend, cfg.model)
        r = promote.run(store, backend, cfg.claude_home, dry_run=getattr(a, "dry_run", False), include_quiet=getattr(a, "include_quiet", False))
        label = "후보 세션" if getattr(a, "dry_run", False) else "episode"
        print(f"세션 {r.scanned}개 확인 · 신호 없음 {r.skipped_no_signal} · LLM 호출 {r.llm_calls} · {label} {len(r.episodes)}")
        for e in r.episodes:
            print(f"  + {e}")
        for e in r.errors:
            print(f"  ! {e}")
        if a.cmd == "run":
            path = reflect.run(store, llm.make(cfg.backend, cfg.model))
            print(f"제안 생성: {path.name}" if path else "reflect: 새 episode 없음")
            print(health.render(health.write(store)))
    elif a.cmd == "reflect":
        path = reflect.run(store, None if a.dry_run else llm.make(cfg.backend, cfg.model), dry_run=a.dry_run)  # type: ignore[arg-type]
        if path:
            print(f"제안 생성: {path.name} → `amem review`로 확인")
        elif not a.dry_run:
            print("새 episode 없음")
    elif a.cmd == "review":
        ps = review.proposals(store)
        if not ps:
            print("승인 대기 제안 없음")
        for p in ps:
            print(f"■ {p['id']} ({p['machine']}, {p['created_at'][:16]})")
            for it in p["items"]:
                if it["status"] == "pending":
                    print(f"  {it['n']:>2}. {review.describe(it)}")
        if ps:
            print("\n승인: amem apply <id> [--only 1,2]   거절: amem reject <id> [--only 3]")
    elif a.cmd == "apply":
        for line in review.decide(store, a.proposal, accept=True, only=only):
            print(line)
        health.write(store)
    elif a.cmd == "reject":
        for line in review.decide(store, a.proposal, accept=False, only=only):
            print(line)
    elif a.cmd == "export":
        target = export.memory_dir(cfg.claude_home)
        lines = export.run(store, a.store, target, cfg.export_threshold)
        print(f"{len(lines)}개 내보냄 → {target}")
        for line in lines:
            print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
