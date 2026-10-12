import { test, expect, mock } from 'claude-code/testing'

const H = (experience: number, opinion: number, pending: number) => JSON.stringify({
  machine: 'mac', counts: { world: 0, experience, observation: 0, opinion, procedure: 0 },
  new_today: 0, updated_today: 0, conflicts: [], pending_sessions: 0, fresh_episodes: 0, pending_proposals: pending,
  recent_changes: [{ id: 'op_1', label: '원문 단위 보존', from: null, to: 0.86, at: '2026-10-12T12:00:00+09:00' }],
})
const PROPOSAL = JSON.stringify({ id: 'p1', status: 'pending', items: [{ n: 1, op: 'new_opinion', status: 'pending', statement: 'E2E는 운영 데이터로', supports: ['a', 'b'], contradicts: [] }] })

// 가짜 파일시스템: personal(경험 6) + work(경험 25, 제안 1)
const FILES: Record<string, string> = {
  '/Users/a/workspace/memory-personal/.amem/health-mac.json': H(6, 0, 0),
  '/Users/a/workspace/memory-work/.amem/health-mac.json': H(25, 10, 1),
  '/Users/a/workspace/memory-work/proposals/p1.json': PROPOSAL,
}
const DIRS = ['/Users/a/workspace/memory-personal', '/Users/a/workspace/memory-work', '/Users/a/workspace/memory-work/proposals']

test('pane에 personal과 work가 함께 보이고 work 제안에 승인 버튼이 있다', async ($, on) => {
  mock.env(on, { HOME: '/Users/a' })
  on('fs.exists', ($, e) => ({ value: e.path in FILES || DIRS.includes(e.path) }) as never)
  on('fs.read', ($, e) => ({ value: FILES[e.path] ?? '' }) as never)
  on('fs.list', ($, e) => ({ value: e.path.endsWith('/proposals') ? [{ name: 'p1.json', kind: 'file', size: 1, mtimeMs: 0 }] : [] }) as never)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'memory-lens', surface, component: 'Pane', requestId: 'memory-lens', props: { title: 'm' } as never })
    await ui.press({ key: 'refresh' })
    expect(await ui.find({ type: 'Text', text: /경험 25 · 판단 10/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /경험 6 · 판단 0/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /E2E는 운영 데이터로/ })).toBeDefined()
    expect(await ui.find({ key: 'ok-work-p1-1' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /NEW 원문 단위 보존 0.86/ })).toBeDefined()
    await ui.unmount()
  }
})
