import { test, expect } from 'claude-code/testing'
import { correctionOf, eventFile, norm, scopeOf, targetOf } from './core.ts'

test('윈도우/맥 경로 정규화', () => {
  expect(norm('C:\\Users\\jung\\workspace\\')).toBe('C:/Users/jung/workspace')
  expect(norm('/Users/a/ws/')).toBe('/Users/a/ws')
})

test('scope 판정: 업무 경로 우선, 윈도우 대소문자 무시', () => {
  expect(scopeOf('C:\\Work\\acme\\api', 'c:/work, D:\\clients', 'personal')).toBe('work')
  expect(scopeOf('D:\\clients\\client-a', 'c:/work, D:\\clients', 'personal')).toBe('work')
  expect(scopeOf('C:\\Workshop', 'c:/work', 'personal')).toBe('personal')
  expect(scopeOf('/Users/a/side', '', 'work')).toBe('work')
  expect(scopeOf('/Users/a/side', '', 'personal')).toBe('personal')
})

test('교정 신호는 키워드만', () => {
  expect(correctionOf('아니 그게 아니라 B로 해')).toBe('아니')
  expect(correctionOf('그거 말고 다른 거')).toBe('그거 말고')
  expect(correctionOf('No, use the other one')).toBe('no')
  expect(correctionOf('틀렸어 다시')).toBe('틀렸어')
  expect(correctionOf('아니메이션 만들어줘')).toBeNull()
  expect(correctionOf('좋아 다음 단계')).toBeNull()
})

test('대상은 상대경로/명령 이름만 (인자·비밀값 버림)', () => {
  expect(targetOf('Edit', { file_path: 'C:\\ws\\app\\src\\a.ts' }, 'C:\\ws\\app')).toBe('src/a.ts')
  expect(targetOf('Read', { file_path: '/etc/hosts' }, '/Users/a/ws')).toBe('hosts')
  expect(targetOf('Bash', { command: 'git commit -m "secret token"' }, '/x')).toBe('git commit')
  expect(targetOf('Bash', { command: 'curl -H "Authorization: abc" x' }, '/x')).toBe('curl')
  expect(targetOf('WebSearch', { query: 'q' }, '/x')).toBeUndefined()
  expect(targetOf('Bash', { command: 'AWS_SECRET_ACCESS_KEY=abc aws s3 ls' }, '/x')).toBe('aws')
  expect(targetOf('Bash', { command: 'TOKEN=xyz' }, '/x')).toBeUndefined()
  expect(targetOf('Bash', { command: './scripts/deploy.sh prod' }, '/x')).toBe('deploy.sh')
  expect(targetOf('Bash', { command: 'C:\\tools\\run.exe' }, '/x')).toBe('run.exe')
  expect(targetOf('Bash', { command: 'git --git-dir=/secret status' }, '/x')).toBe('git')
  expect(targetOf('Bash', { command: 'echo "$(cat ~/.ssh/id)"' }, '/x')).toBe('echo')
})

test('세션별 파일 경로', () => {
  expect(eventFile('C:\\mem\\work', 'win-work', '2026-10-12T09:00:00+09:00', 'abcdef1234')).toBe('C:/mem/work/events/win-work/2026-10-12_abcdef12.jsonl')
})
