import { test, expect } from 'claude-code/testing'
import { classifyPath, memoryType, paths } from './parse.ts'

test('frontmatter type 추출', () => {
  expect(memoryType('a.md', '---\nname: x\ntype: feedback\n---\nbody')).toBe('feedback')
  expect(memoryType('a.md', '---\nmetadata:\n  type: project\n---\n')).toBe('project')
  expect(memoryType('a.md', '---\ntags: [memory/reference]\n---\n')).toBe('reference')
  expect(memoryType('user_role.md', 'no frontmatter')).toBe('user')
  expect(memoryType('notes.md', '')).toBe('other')
})

test('기억/스킬 경로 판정', () => {
  expect(classifyPath('/Users/a/.claude/projects/-Users-a/memory/feedback_x.md')).toEqual({ kind: 'memory', name: 'feedback_x' })
  expect(classifyPath('/Users/a/.claude/projects/-Users-a/memory/MEMORY.md')).toBeNull()
  expect(classifyPath('/Users/a/.claude/skills/report/SKILL.md')).toEqual({ kind: 'skill', name: 'report' })
  expect(classifyPath('/Users/a/workspace/README.md')).toBeNull()
})

test('홈 경로에서 메모리 경로 유도', () => {
  const p = paths('/Users/a')
  expect(p.memoryDir).toBe('/Users/a/.claude/projects/-Users-a/memory')
  expect(p.skillsDir).toBe('/Users/a/.claude/skills')
  const w = paths('C:\\Users\\jung')
  expect(w.memoryDir).toBe('C:/Users/jung/.claude/projects/C--Users-jung/memory')
})

test('윈도우 경로도 기억 저장으로 판정', () => {
  expect(classifyPath('C:\\Users\\jung\\.claude\\projects\\C--Users-jung\\memory\\opinion_x.md')).toEqual({ kind: 'memory', name: 'opinion_x' })
})
