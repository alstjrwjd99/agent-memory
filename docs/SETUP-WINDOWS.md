# 윈도우(회사 PC) 설치

PowerShell 기준. Claude Code에게 "docs/SETUP-WINDOWS.md대로 설치해줘"라고 시켜도 된다.

## 0. 준비물 확인

```powershell
git --version
claude --version
uv --version     # 없으면: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
gh auth status   # public-guard가 저장소 공개 여부를 확인할 때 사용. 안 돼 있으면: gh auth login
```

## 1. 저장소 받기

```powershell
cd $HOME\workspace
git clone https://github.com/alstjrwjd99/agent-memory.git
git clone https://github.com/alstjrwjd99/memory-personal.git
```

## 2. 업무 기억 저장소 (회사 PC 로컬)

업무 기억은 개인 GitHub에 올리지 않는다. 회사 PC에서 새로 만든다 (나중에 회사 승인 저장소가 생기면 원격 연결).

```powershell
mkdir $HOME\workspace\memory-work
cd $HOME\workspace\memory-work
git init
```

## 3. 엔진 설치 + 설정

```powershell
cd $HOME\workspace\agent-memory\engine
uv sync
uv run amem init --machine win-work --personal $HOME\workspace\memory-personal --work $HOME\workspace\memory-work
```

`$HOME\.config\agent-memory\config.yaml`을 열어 `work_paths`에 회사 저장소 폴더들을 넣는다:

```yaml
work_paths:
- C:\Users\<사용자>\workspace\<회사 저장소1>
- C:\Users\<사용자>\workspace\<회사 저장소2>
```

## 4. mod 설치

```powershell
claude plugin marketplace add $HOME\workspace\agent-memory
claude plugin install memory-events@agent-memory --config machine=win-work --config defaultScope=work --config workStore=$HOME\workspace\memory-work --config personalStore=$HOME\workspace\memory-personal
claude plugin install memory-lens@agent-memory --config machine=win-work
claude plugin install public-guard@agent-memory
claude plugin install env-guard@agent-memory
```

- memory-lens의 `machine=win-work`는 필수. 빠지면 패널이 health 파일을 못 찾아 비어 보인다.
- memory-events의 `workPaths`에도 3번과 같은 회사 저장소 폴더를 쉼표로 넣으면 좋다 (`/config`에서 수정 가능).

## 5. 민감어 목록 (저장소에 없음, 직접 만들기)

`$HOME\.config\agent-memory\sensitive-terms.txt`: 공개 저장소로 나가면 안 되는 고객사·내부 프로젝트명을 한 줄에 하나씩. 맥의 같은 파일 내용을 그대로 옮긴다.

## 6. 확인

Claude Code에서:

```
/reload-plugins
/memory-lens      → 오른쪽 패널에 personal / work 가 보이면 정상
/flow             → 패널 맨 위에 작업 흐름
```

터미널에서:

```powershell
cd $HOME\workspace\agent-memory\engine
uv run amem health
uv run amem --store work health
```

## 7. (선택) 회사 저장소 과거 기록으로 원칙 만들기

```powershell
uv run amem ingest git $HOME\workspace\<회사 저장소> --since 2026-09-01   # 경험 추출 (store는 work_paths로 자동 선택)
uv run amem --store work distill                                           # 원칙 정리
uv run amem --store work heuristics                                        # 결과 보기
```

## 평소 사용

- 작업 전후: `uv run amem sync` (개인 기억 동기화)
- 주 1회: 패널 ✨ → 원칙 후보 승인/거절
- 코드 업데이트: `git -C $HOME\workspace\agent-memory pull` 후 `/reload-plugins`

## 윈도우에서 아직 검증 안 된 것

- `claude -p` 호출 (`claude.exe` 우선 탐색, JSON 인자 따옴표)
- 패널이 엔진을 `.venv\Scripts\amem.exe`로 직접 실행하는 경로
- 막히면 에러 메시지를 그대로 Claude에게 보여주고 고칠 것
