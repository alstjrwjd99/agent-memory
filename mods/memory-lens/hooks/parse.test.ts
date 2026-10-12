import { test, expect } from 'claude-code/testing'
import { changeLine, classifyPath, describe, pendingItems, resolvePaths, shouldRecall } from './parse.ts'

test('기억/스킬 경로 판정 (맥/윈도우)', () => {
  expect(classifyPath('/Users/a/.claude/projects/-Users-a/memory/feedback_x.md')).toEqual({ kind: 'memory', name: 'feedback_x' })
  expect(classifyPath('/Users/a/.claude/projects/-Users-a/memory/MEMORY.md')).toBeNull()
  expect(classifyPath('/Users/a/.claude/skills/report/SKILL.md')).toEqual({ kind: 'skill', name: 'report' })
  expect(classifyPath('C:\\Users\\j\\.claude\\projects\\C--Users-j\\memory\\op.md')).toEqual({ kind: 'memory', name: 'op' })
  expect(classifyPath('/Users/a/workspace/README.md')).toBeNull()
})

test('기본 경로는 홈 기준, 설정값이 있으면 그대로', () => {
  expect(resolvePaths('C:\\Users\\j', '', '')).toEqual({ store: 'C:/Users/j/workspace/memory-personal', workStore: 'C:/Users/j/workspace/memory-work', engineDir: 'C:/Users/j/workspace/agent-memory/engine' })
  expect(resolvePaths('/Users/a', 'D:\\mem\\p\\', '/e', 'D:\\mem\\work')).toEqual({ store: 'D:/mem/p', workStore: 'D:/mem/work', engineDir: '/e' })
})

test('승인 대기 항목만, 깨진 파일은 무시', () => {
  const p = JSON.stringify({
    id: 'p1', status: 'pending',
    items: [
      { n: 1, op: 'new_opinion', status: 'pending', statement: 'S', supports: ['a', 'b'], contradicts: [] },
      { n: 2, op: 'observe', status: 'applied', subject: 'x', summary: 'y' },
      { n: 3, op: 'new_procedure', status: 'pending', trigger: 'T', rules: ['a'] },
    ],
  })
  const done = JSON.stringify({ id: 'p0', status: 'done', items: [] })
  expect(pendingItems([p, done, '{broken'], 'work')).toEqual([
    { scope: 'work', pid: 'p1', n: 1, text: '[판단 0.75] S' },
    { scope: 'work', pid: 'p1', n: 3, text: '[절차] T' },
  ])
  expect(describe({ n: 1, op: 'evidence', status: 'pending', id: 'op_1', supports: ['a'], contradicts: [] })).toBe('[근거] op_1 +1 / 반례 +0')
})

test('recall 대상 프롬프트 판정', () => {
  expect(shouldRecall('ㄱㄱ')).toBe(false)
  expect(shouldRecall('/memory-lens')).toBe(false)
  expect(shouldRecall('recall 만들어줘 그리고 버전 관리도')).toBe(true)
})

test('판단 변화 표시', () => {
  expect(changeLine({ label: 'UI 먼저', from: 0.62, to: 0.78 }, 20)).toBe('↑ UI 먼저 0.62→0.78')
  expect(changeLine({ label: 'x', from: 0.81, to: 0.54 }, 20)).toBe('↓ x 0.81→0.54')
  expect(changeLine({ label: '아주아주긴판단문장입니다', from: null, to: 0.8 }, 6)).toBe('NEW 아주아주긴… 0.80')
})
