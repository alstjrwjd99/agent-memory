import { test, expect } from 'claude-code/testing'
import { expandHome, findTerms, isPublishing, locate, parseTerms, parseVisibility, repoDirOf } from './scan.ts'

test('commit/push 명령 감지', () => {
  expect(isPublishing('git add -A && git commit -q -m "x" && git push -q')).toBe(true)
  expect(isPublishing('git -C ~/w/repo push --force-with-lease')).toBe(true)
  expect(isPublishing('git status && git log')).toBe(false)
  expect(isPublishing('echo "git commit" | cat')).toBe(false)
})

test('저장소 경로 해석', () => {
  expect(repoDirOf('git -C ~/workspace/agent-memory push')).toBe('~/workspace/agent-memory')
  expect(repoDirOf('cd "/Users/a/my repo" && git commit -m x')).toBe('/Users/a/my repo')
  expect(repoDirOf('git commit -m x')).toBeNull()
  expect(expandHome('~/w', '/Users/a')).toBe('/Users/a/w')
})

test('민감어: 영문은 단어 경계, 한글은 포함', () => {
  const terms = parseTerms('# 고객사\nacmecorp\n가나다\n\nZX12345Q  # 프로젝트 코드\n')
  expect(terms).toEqual(['acmecorp', '가나다', 'ZX12345Q'])
  expect(findTerms("project: 'acmecorp', acmecorp-catalyst", terms)).toEqual(['acmecorp'])
  expect(findTerms('acmecorpseconds and Acmecorporation', terms)).toEqual([])
  expect(findTerms('가나다APC 레시피', terms)).toEqual(['가나다'])
  expect(findTerms('case ZX12345Q worst', terms)).toEqual(['ZX12345Q'])
})

test('공개 여부 해석과 위치 찾기', () => {
  expect(parseVisibility('{"isPrivate":false,"visibility":"PUBLIC"}')).toBe('public')
  expect(parseVisibility('{"isPrivate":true,"visibility":"PRIVATE"}')).toBe('private')
  expect(parseVisibility('garbage')).toBe('unknown')
  const diff = '+++ b/a.ts\n+ok\n+++ b/test/x.ts\n+const p = "acmecorp"\n'
  expect(locate(diff, 'acmecorp')).toEqual(['test/x.ts'])
})
