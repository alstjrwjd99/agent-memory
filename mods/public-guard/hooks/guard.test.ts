import { test, expect, mock } from 'claude-code/testing'
import type { On } from 'claude-code'

// git/gh/파일을 가짜로: 공개 저장소, 업스트림 대비 diff에 민감어가 있는 상황
function world(on: On, opts: { isPrivate: boolean; diff: string; terms?: string }) {
  mock.env(on, { HOME: '/Users/a' })
  on('session.cwd', () => ({ value: '/Users/a/w/repo' }) as never)
  on('fs.exists', ($, e) => ({ value: e.path === '/Users/a/.config/agent-memory/sensitive-terms.txt' }) as never)
  on('fs.read', () => ({ value: opts.terms ?? 'acmecorp\n가나다\n' }) as never)
  on('process.run', ($, e) => {
    const a = e.argv.join(' ')
    const out = (stdout: string, exitCode = 0) => ({ value: { exitCode, stdout, stderr: '' } }) as never
    if (a.startsWith('gh repo view')) return out(JSON.stringify({ isPrivate: opts.isPrivate }))
    if (a.includes('remote get-url')) return out('https://github.com/me/repo.git\n')
    if (a.includes('rev-parse --abbrev-ref')) return out('origin/main\n')
    if (a.includes(' diff origin/main')) return out(opts.diff)
    return out('')
  })
  // 실제 Bash 실행 대신
  on('tool.call', () => ({ result: 'ran' }) as never)
}

test('공개 저장소 + 민감어 → push 차단, 파일 위치 안내', async ($, on) => {
  world(on, { isPrivate: false, diff: '+++ b/test/pane.test.tsx\n+project: "acmecorp"\n' })
  const r = await $.tool.call({ tool: 'Bash', command: 'git push -q' })
  expect(r.deny).toContain('acmecorp (test/pane.test.tsx)')
})

test('비공개 저장소는 통과', async ($, on) => {
  world(on, { isPrivate: true, diff: '+project: "acmecorp"\n' })
  const r = await $.tool.call({ tool: 'Bash', command: 'git push -q' })
  expect(r.deny).toBeUndefined()
})

test('커밋 메시지에만 있어도 차단, 민감어 없으면 통과', async ($, on) => {
  world(on, { isPrivate: false, diff: '+ok\n' })
  const bad = await $.tool.call({ tool: 'Bash', command: 'git commit -m "가나다 레시피 반영"' })
  expect(bad.deny).toContain('가나다')
  const good = await $.tool.call({ tool: 'Bash', command: 'git commit -m "레시피 반영"' })
  expect(good.deny).toBeUndefined()
})
