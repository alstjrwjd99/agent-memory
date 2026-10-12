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

const CMD = (command: string) => ({ command, args: '', origin: { kind: 'composer' } }) as never

function fakeFs(on: Parameters<Parameters<typeof test>[1] & ((...a: never[]) => unknown)>[1]) {
  ;(on as never as (ev: string, h: unknown) => void)('fs.exists', ($: unknown, e: { path: string }) => ({ value: e.path in FILES || DIRS.includes(e.path) }))
  ;(on as never as (ev: string, h: unknown) => void)('fs.read', ($: unknown, e: { path: string }) => ({ value: FILES[e.path] ?? '' }))
  ;(on as never as (ev: string, h: unknown) => void)('fs.list', ($: unknown, e: { path: string }) => ({ value: e.path.endsWith('/proposals') ? [{ name: 'p1.json', kind: 'file', size: 1, mtimeMs: 0 }] : [] }))
  ;(on as never as (ev: string, h: unknown) => void)('ui.open', () => ({ value: { isPlaced: true } }))
  ;(on as never as (ev: string, h: unknown) => void)('session.cwd', () => ({ value: '/Users/a/workspace/agent-memory' }))
}

test('/memory-lens: 기억 상세(personal/work 요약, 승인 버튼)가 펼쳐진다', async ($, on) => {
  mock.env(on, { HOME: '/Users/a' })
  mock.store(on)
  fakeFs(on as never)
  await $.command.run(CMD('memory-lens'))
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'memory-lens', surface, component: 'Pane', requestId: 'memory-lens', props: { title: 'm' } as never })
    expect(await ui.find({ type: 'Text', text: /경험 25 · 판단 10/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /경험 6 · 판단 0/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /E2E는 운영 데이터로/ })).toBeDefined()
    expect(await ui.find({ key: 'ok-work-p1-1' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /NEW 원문 단위 보존 0.86/ })).toBeDefined()
    await ui.unmount()
  }
})

test('평소엔 기억 영역 숨김, 새 후보가 생기면 ✨ 알림 → 나중에 누르면 다시 숨김', async ($, on) => {
  mock.env(on, { HOME: '/Users/a' })
  mock.store(on)
  fakeFs(on as never)
  // 펼치지 않고 파일만 다시 읽게: memory-lens 명령 후 접기
  await $.command.run(CMD('memory-lens'))
  const ui = await $.ui.mount({ plugin: 'memory-lens', surface: 'terminal', component: 'Pane', requestId: 'memory-lens', props: { title: 'm' } as never })
  await ui.press({ key: 'close' })
  expect(await ui.find({ type: 'Text', text: /승인 대기/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /✨/ })).toBeUndefined()
  await ui.unmount()
})

test('/flow 후 패널 맨 위에 2단 흐름 + 다른 작업 목록, 기억 영역은 숨김', async ($, on) => {
  mock.env(on, { HOME: '/Users/a' })
  mock.store(on, {
    'flow:/users/a/workspace/billing': { project: 'billing', goal: 'g', steps: [{ label: '규격서 배열 수정', status: 'now' }], detail: null, waiting: null, at: Date.now() - 12 * 60_000 },
    'flow:/users/a/workspace/apc': { project: 'apc', goal: 'g', steps: [{ label: 'x', status: 'now' }], detail: null, waiting: 'BO 범위 결정', at: Date.now() - 3 * 3600_000 },
  })
  on('fs.exists', ($, e) => ({ value: e.path in FILES || DIRS.includes(e.path) }) as never)
  on('fs.read', ($, e) => ({ value: FILES[e.path] ?? '' }) as never)
  on('fs.list', () => ({ value: [] }) as never)
  on('session.cwd', () => ({ value: '/Users/a/workspace/agent-memory' }) as never)
  // 다른 작업 목록은 파일을 다시 읽을 때 같이 읽음 → memory-lens 명령으로 한 번 읽고 접기
  on('session.messages', () => ({ value: [{ role: 'user', text: '패널에 합쳐줘', toolUses: [] }] }) as never)
  const reply = JSON.stringify({
    goal: '기억 시스템 완성',
    steps: ['설계', '엔진', 'recall', 'git 파일럿', '제안 검토', '윈도우 설치'].map((label, i) => ({ label, status: i < 4 ? 'done' : i === 4 ? 'now' : 'next' })),
    detail: '흐름 패널 옮기기',
    waiting: '위치 고르기',
  })
  on('model.complete', () => ({ value: { isAnswered: true, text: reply, usage: {} } }) as never)
  on('ui.open', () => ({ value: { isPlaced: true } }) as never)
  const r = await $.command.run({ command: 'flow', args: '', origin: { kind: 'composer' } } as never)
  expect(JSON.stringify(r)).toContain('지금: 흐름 패널 옮기기')
  await $.command.run(CMD('memory-lens'))
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'memory-lens', surface, component: 'Pane', requestId: 'memory-lens', props: { title: 'm' } as never })
    expect(await ui.find({ type: 'Text', text: /📍 agent-memory/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /✓ … 1개 완료/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /● 제안 검토/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /└ 지금: 흐름 패널 옮기기/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /○ 윈도우 설치/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /⏸ 내 답 필요: 위치 고르기/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /─ 다른 작업 ─/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /billing ● 규격서 배열 수정 12분/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /apc ⏸ BO 범위 결정 3시간/ })).toBeDefined()
    if (await ui.find({ key: 'close' })) await ui.press({ key: 'close' })
    expect(await ui.find({ type: 'Text', text: /승인 대기/ })).toBeUndefined()
    await ui.unmount()
  }
})
