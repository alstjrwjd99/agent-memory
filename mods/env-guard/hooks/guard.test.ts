import { test, expect } from 'claude-code/testing'
import { findEnvFiles } from './guard.ts'

test('.env 직접 add는 잡는다', () => {
  expect(findEnvFiles('git add .env')).toEqual(['.env'])
  expect(findEnvFiles('git add -f api/.env.local src/a.ts')).toEqual(['api/.env.local'])
  expect(findEnvFiles('cd x && git add ".env.production" && git commit -m hi')).toEqual(['.env.production'])
  expect(findEnvFiles('git commit .env -m wip')).toEqual(['.env'])
  expect(findEnvFiles('git add api\\.env.local')).toEqual(['api\\.env.local'])
})

test('템플릿과 무관한 명령은 통과', () => {
  expect(findEnvFiles('git add .env.example')).toEqual([])
  expect(findEnvFiles('git add src/env.ts README.md')).toEqual([])
  expect(findEnvFiles('cat .env')).toEqual([])
  expect(findEnvFiles('git status')).toEqual([])
})

test('Bash 호출이 실제로 deny된다', async ($, on) => {
  on('tool.call', () => ({ result: 'ran' }) as never)
  const blocked = await $.tool.call({ tool: 'Bash', command: 'git add .env' })
  expect(blocked.deny).toContain('.env 파일은 커밋 금지')
  const passed = await $.tool.call({ tool: 'Bash', command: 'git add README.md' })
  expect(passed.deny).toBeUndefined()
})
