import { test, expect, mock } from 'claude-code/testing'
import type { On } from 'claude-code'

const HIT = { id: 'op_1', kind: 'opinion', score: 3.2, why: ['키워드 2.1'], label: 'UI는 사용자부터' }

// 엔진(uv run amem recall) 호출을 가짜 응답으로 대신하고, 프롬프트에 붙은 context를 확인
function stub(on: On, env: Record<string, string>, stdout: string, seen: { argv: (readonly string[])[]; context: (readonly string[] | undefined)[] }) {
  mock.env(on, env)
  on('session.cwd', () => ({ value: '/Users/a/workspace/acme' }) as never)
  on('fs.exists', () => ({ value: false }) as never)
  on('process.run', ($, e) => {
    seen.argv.push(e.argv)
    return { value: { exitCode: 0, stdout, stderr: '' } } as never
  })
  on('prompt.submit', ($, e) => {
    seen.context.push(e.context)
    return { text: e.text, context: e.context }
  })
}

test('관련 기억이 있으면 보이지 않는 context로 붙는다', async ($, on) => {
  const seen = { argv: [] as (readonly string[])[], context: [] as (readonly string[] | undefined)[] }
  stub(on, { HOME: '/Users/a' }, JSON.stringify({ scope: 'personal', context: '[agent-memory recall] - 판단', hits: [HIT] }), seen)
  await $.prompt.submit({ text: 'UI 화면 설계 어떻게 할까?' } as never)
  // 테스트 환경엔 venv가 없으므로 uv run 경로
  expect(seen.argv[0]?.slice(0, 6)).toEqual(['uv', 'run', '--project', '/Users/a/workspace/agent-memory/engine', 'amem', 'recall'])
  expect(seen.argv[0]).toContain('/Users/a/workspace/acme')
  expect(seen.context[0]).toEqual(['[agent-memory recall] - 판단'])
})

test('짧은 대답, 엔진 내부 호출, 관련 기억 없음은 그대로 통과', async ($, on) => {
  const seen = { argv: [] as (readonly string[])[], context: [] as (readonly string[] | undefined)[] }
  stub(on, { HOME: '/Users/a' }, JSON.stringify({ scope: 'personal', context: '', hits: [] }), seen)
  await $.prompt.submit({ text: 'ㄱㄱ' } as never)
  await $.prompt.submit({ text: '관련 없는 아주 다른 질문입니다' } as never)
  expect(seen.argv.length).toBe(1)
  expect(seen.context).toEqual([undefined, undefined])
})

test('엔진이 띄운 claude -p 세션(AMEM_INTERNAL)에는 recall 안 함', async ($, on) => {
  const seen = { argv: [] as (readonly string[])[], context: [] as (readonly string[] | undefined)[] }
  stub(on, { HOME: '/Users/a', AMEM_INTERNAL: '1' }, '{}', seen)
  await $.prompt.submit({ text: '이 세션에서 episode를 추출하라' } as never)
  expect(seen.argv.length).toBe(0)
})

test('엔진 실패해도 프롬프트는 막히지 않는다', async ($, on) => {
  const seen = { argv: [] as (readonly string[])[], context: [] as (readonly string[] | undefined)[] }
  stub(on, { HOME: '/Users/a' }, 'not json', seen)
  await $.prompt.submit({ text: '이건 정상적인 긴 질문이에요' } as never)
  expect(seen.context).toEqual([undefined])
})
