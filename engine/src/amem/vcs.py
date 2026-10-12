"""store 버전 관리: 엔진이 store를 바꿀 때마다 git 커밋 (푸시는 sync로 사용자가 명시적으로)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


# 엔진이 쓰는 경로만 커밋 (events/는 세션 중 계속 쓰이는 원본 로그라 git에 넣지 않음)
TRACKED = ["episodes", "world", "observations", "opinions", "procedures", "proposals", ".gitignore"]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8")


def _identity(root: Path) -> list[str]:
    """새 윈도우 PC처럼 user.name이 없으면 커밋이 실패하므로 대체 신원 사용. 서명 프롬프트로 멈추지 않게 gpgsign 끔."""
    args = ["-c", "commit.gpgsign=false"]
    if not _git(root, "config", "user.name").stdout.strip():
        args += ["-c", "user.name=amem", "-c", "user.email=amem@localhost"]
    return args


class CommitError(RuntimeError):
    pass


def is_repo(root: Path) -> bool:
    return shutil.which("git") is not None and (root / ".git").exists()


def commit(root: Path, message: str) -> str | None:
    """변경이 있으면 커밋하고 짧은 해시 반환. git 저장소가 아니면 아무것도 안 함."""
    if not is_repo(root):
        return None
    paths = [p for p in TRACKED if (root / p).exists()]
    # PC별 처리 상태 파일 (processed-<pc>, ingest-*-<pc>)
    paths += [str(p.relative_to(root).as_posix()) for pat in ("processed-*.json", "ingest-*.json") for p in (root / ".amem").glob(pat)]
    _git(root, "add", "-A", "--", *paths)
    if _git(root, "diff", "--cached", "--quiet").returncode == 0:
        return None
    r = _git(root, *_identity(root), "commit", "-q", "-m", message)
    if r.returncode != 0:
        raise CommitError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"exit {r.returncode}")
    return _git(root, "rev-parse", "--short", "HEAD").stdout.strip()


def history(root: Path, rel: str) -> str:
    """한 기억 파일의 변경 이력 (파일 내용 diff 포함)."""
    if not is_repo(root):
        return "(git 저장소 아님)"
    r = _git(root, "log", "--follow", "--date=short", "--format=── %h %ad %s", "-p", "--", rel)
    return r.stdout.strip() or "(이력 없음)"


def sync(root: Path) -> str:
    """pull --rebase 후 push. 원격이 없으면 안내만."""
    if not is_repo(root):
        return "git 저장소 아님"
    if not _git(root, "remote").stdout.strip():
        return "원격 저장소 없음: git remote add origin <private 저장소 URL>"
    try:
        commit(root, "amem: sync 전 정리")
    except CommitError as e:
        return f"커밋 실패로 sync 중단: {e}"
    pull = _git(root, "pull", "--rebase", "--autostash", "-q")
    if pull.returncode != 0:
        return f"pull 실패 (충돌 확인 필요): {pull.stderr.strip()[:300]}"
    push = _git(root, "push", "-q")
    return "동기화 완료" if push.returncode == 0 else f"push 실패: {push.stderr.strip()[:300]}"
