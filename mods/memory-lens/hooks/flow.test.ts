import { test, expect } from 'claude-code/testing'
import { buildPrompt, parseFlow, projectOf, stepsLine, storeKey, transcriptDigest, verticalSteps } from './flow.ts'

const S = (label: string, status: 'done' | 'now' | 'next') => ({ label, status })

test('모델 응답 파싱: 앞뒤 잡음 무시, 잘못된 단계 제거, null 문자열 처리', () => {
  const f = parseFlow('결과:\n{"goal":"reflect 개선","steps":[{"label":"설계","status":"done"},{"label":"x","status":"bad"},{"label":"기준 수정","status":"now"}],"waiting":"null"} 끝', 'agent-memory', 1)
  expect(f).toEqual({ project: 'agent-memory', goal: 'reflect 개선', steps: [S('설계', 'done'), S('기준 수정', 'now')], detail: null, waiting: null, at: 1 })
  expect(parseFlow('json 아님', 'p', 1)).toBeNull()
  expect(parseFlow('{"goal":"g","steps":[]}', 'p', 1)).toBeNull()
  expect(parseFlow('{"goal":"g","steps":[{"label":"a","status":"now"}],"waiting":"14개 거절할지"}', 'p', 1)?.waiting).toBe('14개 거절할지')
})

test('흐름 한 줄: 넓으면 전부, 좁으면 지금 단계 중심으로 줄임', () => {
  const steps = [S('설계', 'done'), S('엔진', 'done'), S('recall', 'done'), S('git 파일럿', 'done'), S('reflect 수정', 'now'), S('윈도우 설치', 'next'), S('Notion', 'next')]
  expect(stepsLine(steps, 200)).toBe('✓ 설계 → ✓ 엔진 → ✓ recall → ✓ git 파일럿 → ● reflect 수정 → ○ 윈도우 설치 → ○ Notion')
  const narrow = stepsLine(steps, 40)
  expect(narrow.length).toBeLessThanOrEqual(40)
  expect(narrow).toContain('● reflect 수정')
  expect(narrow.startsWith('… ')).toBe(true)
  expect(stepsLine(steps, 8)).toBe('● reflec')
})

test('대화 요약: 최근 N개, 도구 이름, 길이 제한', () => {
  const msgs = Array.from({ length: 50 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', text: `메시지 ${i} ` + 'x'.repeat(1000), toolUses: i === 49 ? [{ tool: 'Bash' }] : [] }))
  const d = transcriptDigest(msgs, 40, 50)
  expect(d.split('\n').length).toBe(40)
  expect(d).toContain('(도구: Bash)')
  expect(d).not.toContain('메시지 9 ')
  expect(buildPrompt(d, null)).toContain('(없음)')
})

test('프로젝트 이름과 저장 키 (맥/윈도우)', () => {
  expect(projectOf('C:\\work\\acme\\')).toBe('acme')
  expect(projectOf('/Users/a/workspace/agent-memory')).toBe('agent-memory')
  expect(storeKey('C:\\Work\\Acme')).toBe('flow:c:/work/acme')
})

test('2단 흐름: detail 파싱, 끝난 단계 접기', () => {
  const f = parseFlow('{"goal":"기억 시스템 완성","steps":[{"label":"a","status":"done"},{"label":"b","status":"now"}],"detail":"흐름 패널 옮기기","waiting":null}', 'p', 1)
  expect(f?.detail).toBe('흐름 패널 옮기기')
  const v = verticalSteps([S('1', 'done'), S('2', 'done'), S('3', 'done'), S('4', 'done'), S('5', 'done'), S('6', 'now'), S('7', 'next')], 3)
  expect(v[0]).toEqual({ kind: 'folded', count: 2 })
  expect(v.map(x => (x.kind === 'step' ? x.label : '…'))).toEqual(['…', '3', '4', '5', '6', '7'])
})
