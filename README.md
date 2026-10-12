# agent-memory

에이전트의 경험 → 사실 → 판단 → 행동 규칙을 쌓는 메모리 시스템 + Claude Code mods. 설계: [docs/DESIGN.md](docs/DESIGN.md)

## 설치 (Mac / Windows 공통)
```
git clone <이 저장소> ~/workspace/agent-memory
claude plugin marketplace add ~/workspace/agent-memory
claude plugin install memory-events@agent-memory
claude plugin install memory-lens@agent-memory
claude plugin install env-guard@agent-memory
```
로컬 폴더 marketplace라 `git pull` 후 세션에서 `/reload-plugins`만 하면 반영됨.

## 엔진 (amem)
```
cd engine
uv sync
uv run amem init --machine mac --personal ~/workspace/memory-personal          # 맥
uv run amem init --machine win-work --work C:\work\memory-work --personal ...  # 윈도우
uv run amem health
uv run amem promote            # events → episode (신호 있는 세션만 LLM 호출)
uv run amem reflect            # 판단 변화 제안 생성
uv run amem review             # 제안 확인
uv run amem apply <id> --only 1,3   /  uv run amem reject <id>
uv run amem export             # 확신도 높은 판단을 Claude Code 메모리로
uv run amem recall "질문" --cwd .   # 관련 기억 꺼내기 (memory-lens가 프롬프트마다 자동 호출)
uv run amem history <id>       # 한 기억의 변천 (versions + 확신도 + git diff)
uv run amem sync               # store git pull --rebase + push
uv run amem --store work ...   # 업무 store 대상
```
설정: `~/.config/agent-memory/config.yaml` (윈도우: `%USERPROFILE%\.config\agent-memory\config.yaml`)

## memory-events 설정 (`/config` 또는 settings.json `pluginConfigs`)
| 필드 | Mac | Windows(회사) |
|---|---|---|
| machine | mac | win-work |
| defaultScope | personal | work |
| personalStore | ~/workspace/memory-personal 절대경로 | (개인 store 경로) |
| workStore | (비움) | C:\...\memory-work |
| workPaths | (비움) | 필요 시 |
