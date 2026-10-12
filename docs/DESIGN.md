# agent-memory 설계

Memory = 모든 걸 저장하는 시스템이 아니라 **경험 → 사실 → 판단 → 행동 규칙으로 압축되는 시스템**.
Hindsight(world/experience/observation/opinion + retain/recall/reflect)를 중심축으로, Procedure를 추가한 5종.

## 결정 사항 (2026-10-12)
| 항목 | 결정 | 이유 |
|---|---|---|
| 역할 분리 | mods = Memory UX, engine = retain/recall/reflect 로직 | mod는 샌드박스(Node 없음). 엔진 분리해야 다른 agent에도 재사용 |
| events | 세션 중 raw event만 기록, episode는 의미 있는 것만 승격 | 턴별 로그는 telemetry지 기억이 아님 |
| events 내용 | 도구명/상대경로/명령이름/성공여부/교정 키워드만. 원문 X | 토큰·비밀값·고객 정보 유출 방지 |
| confidence | LLM이 숫자 생성 X. `(지지+1)/(지지+반례+2)` 계산 | 가짜 정밀도 방지, 두 PC 머지 시 재계산만 하면 됨 |
| 삭제 | DELETE 대신 superseded / invalidated / low_confidence | 판단 진화 이력 보존 |
| 유효기간 | world fact에 valid_from / valid_to / learned_at / source | Graphiti식 temporal validity |
| 저장소 | store를 personal / work 두 git 저장소로 분리 | 회사 정보가 개인 계정에 올라가지 않도록 |
| 기기 | Mac(개인) + Windows(회사) 왕복 | events는 PC별 폴더·세션별 파일 → 머지 충돌 0 |
| recall 경로 | engine store가 원본, `~/.claude/projects/*/memory/`는 export된 view | Claude Code 기본 메모리 로딩 유지 |
| 인덱스 | graph.json / embeddings는 보류 | 현재 규모(수십 개)에선 grep+링크로 충분 |
| Obsidian | 연동 안 함 (거의 안 씀) | |

## 구조
```
agent-memory/            (코드: 개인 private GitHub)
  mods/                  memory-events, memory-lens, env-guard
  engine/                [2단계] Python + uv: promote / reflect / export
  docs/
memory-personal/         (store: 개인 private GitHub)
memory-work/             (store: 회사 승인 저장소)
  events/<machine>/<YYYY-MM-DD>_<session8>.jsonl
  episodes/  world/  observations/  opinions/  procedures/
```

## scope 라우팅 (memory-events)
cwd가 `workPaths` 접두어에 걸리면 work, 아니면 `defaultScope`.
- Mac: defaultScope=personal
- Windows 회사 PC: defaultScope=work, 개인 작업 폴더만 personal로 쓰려면 반대로 설정

## 승격 조건 (events → episode, 2단계 engine)
사용자 교정 / 실패→재시도→성공 / 새 의사결정 / 반복 문제 / 기존 memory와 충돌 / 새 작업 방식 / 결과가 명확히 좋거나 나쁨.
세션 종료 이벤트는 불안정(터미널 강제 종료) → 다음 세션 시작 시 또는 `/reflect`로 미처리분 처리.

## 파일 스키마 (예: opinion)
```yaml
id: op_20261012_mac_001
type: opinion
statement: "신규 프로젝트에서는 세부 규칙보다 motivation을 먼저 파악하는 것이 중요하다"
evidence: [ep_..., ep_...]
counter_evidence: [ep_...]
status: active          # active | superseded | invalidated | low_confidence
valid_from: 2026-04-22
valid_to: null
links: ["[[procedures/project-start]]"]
created_at: 2026-04-22
updated_at: 2026-10-12
```
confidence는 저장하지 않고 evidence/counter_evidence로 계산.

## 엔진 흐름 (engine/, `amem` CLI)
```
events (mod, 자동)
  → amem promote   규칙 신호 감지 → 신호 있는 세션만 LLM이 episode 추출 (+로컬 transcript 발췌)
  → amem reflect   새 episode + 기존 판단 → 제안(proposals/*.json) 생성, 적용 X
  → amem review / apply / reject   사용자 승인 (ADD / 근거 UPDATE / INVALIDATE, DELETE 없음)
  → amem export    conf ≥ 0.7인 opinion/procedure → Claude Code memory 폴더 (amem_*.md + MEMORY.md 관리 블록)
  → amem health    Memory Health (.amem/health-<machine>.json, memory-lens pane이 읽음)

amem recall "<프롬프트>" --cwd <폴더>   (memory-lens가 프롬프트마다 호출, LLM 없음, 약 0.4초)
  → 관련 기억 상위 5개를 프롬프트 옆 보이지 않는 context로 붙임
```

## recall (Hindsight TEMPR 경량판)
- 점수 = BM25(영문 단어 + 한국어 글자 2-gram) × 종류 가중(절차 1.3, 판단 1.2, 관찰 1.0, 경험 0.8)
  × 같은 프로젝트 1.6(cwd 경로 ↔ episode project/관찰 subject) × 확신도(판단) 또는 최신성(반감기 45일)
- 링크 확장: 걸린 episode를 근거로 삼는 판단/관찰도 함께 (그래프 한 단계)
- active만 대상 (invalidated/superseded/low_confidence 제외), 최소 점수 미달이면 아무것도 안 붙임
- store 자동 선택: config `work_paths` 아래 cwd면 work
- 엔진 자신의 `claude -p`(AMEM_INTERNAL=1)에는 recall 안 붙임: 기억이 기억 추출을 오염시키지 않게
- 검색기는 `Retriever` 프로토콜: 임베딩 / 실제 Hindsight로 교체 가능 (의미 검색은 아직 없음)
- pane "이번에 꺼낸 기억"에 무엇을 왜 꺼냈는지 표시 (Memory Inspector)

## 버전 관리
- 엔진이 store를 바꾸는 명령(promote, reflect, run, apply, reject)마다 store git에 자동 커밋. 메시지에 변경 내용
- push는 자동 X: `amem sync` (pull --rebase + push)
- 판단 문장 자체 수정: reflect의 `revisions` → `revise` 제안. 이전 문장은 파일 `versions`와 git 둘 다에 보존
- `amem history <id>`: 파일 내 versions + 확신도 이력 + git diff 이력
- LLM 백엔드: 기본 `claude -p --json-schema` (두 PC의 Claude Code 로그인 재사용, API 키 불필요). `backend: sdk`면 anthropic SDK.
- 엔진의 `claude -p` 호출은 `AMEM_INTERNAL=1`로 띄워 memory-events가 기록하지 않음.
- 신호 종류: correction, interrupted, retry_success, repeated_failure, repeated_sequence(읽기 전용 반복 제외).
- reflect 결과 검증: 존재하지 않는 id 인용 제거, 근거 없는 opinion 버림, procedure는 근거 episode 2개 이상.
- 이미 reflect한 episode는 모든 PC의 proposal 파일 `considered` 목록으로 판단 (공유 상태 파일 없음 → 충돌 없음).
- 처리 상태(`.amem/processed-<machine>.json`)는 PC별 파일.

## 로드맵
0. memory-lens 현황판 ✅
1. memory-events 수집 + 두 PC 설치 ✅(맥) / 윈도우 설치 대기
2. engine: promote, reflect, review, export, health ✅ (2026-10-12, 실제 claude -p로 E2E 확인)
3. Memory Health pane + 승인/거절 버튼 ✅ (memory-lens v0.2)
4. recall 주입 + Memory Inspector + git 버전 관리 ✅ (memory-lens v0.3, 엔진 recall/history/sync)
5. 출처 어댑터: git ✅ (`amem ingest git <repo> --since`), transcript / notion 예정
6. 다음: 의미 검색(임베딩 또는 실제 Hindsight), 윈도우 실사용 검증

## 출처 어댑터 (과거 기록 → episode, 냉시동 해결)
- git: prompt 커밋 ~ 다음 prompt 커밋 = 작업 단위. 커밋 제목/본문 + 변경 파일 목록만 (diff 원문 X)
  - 신호: correction(여전히/다시), external_feedback(피드백), fix_in_unit, outcome_recorded(→), large_unit, reworked_next(다음 단위가 같은 파일 재작업)
  - 신호 없는 단위는 LLM 없이 처리 완료, 8단위씩 묶어 1회 호출, 처리 상태 `.amem/ingest-git-<pc>.json`
  - store는 저장소 경로로 자동 선택 (config work_paths) → 회사 저장소는 work store로만
- 파일럿(회사 저장소 1개, 한 달): 작업 단위 43 → 신호 24 → LLM 3회(2분 19초) → episode 25 → reflect 1회 → 판단 10(conf 0.75~0.86) + 절차 2
