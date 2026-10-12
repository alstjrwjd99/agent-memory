import { test, expect, mock } from 'claude-code/testing'

const REPLY = JSON.stringify({
  goal: 'reflect 품질 개선',
  steps: [{ label: '엔진', status: 'done' }, { label: 'recall', status: 'done' }, { label: '기준 수정', status: 'now' }, { label: '윈도우 설치', status: 'next' }],
  waiting: '제안 14개 거절할지',
})
const PROPS = (rows: number, isWorking = false) => ({ hasSurvey: false, isWorking, maxRows: rows, bodyColumns: 80 }) as never

test('/flow 후 band에 프로젝트, 흐름, 내 답 필요가 보이고 폴더별로 저장된다', async ($, on) => {
  mock.env(on, {})
  mock.store(on)
  on('session.cwd', () => ({ value: '/Users/a/workspace/agent-memory' }) as never)
  on('session.messages', () => ({ value: [{ role: 'user', text: '기준 바꿔서 다시 돌려줘', toolUses: [] }, { role: 'assistant', text: '14개를 거절할까요?', toolUses: [] }] }) as never)
  const prompts: string[] = []
  on('model.complete', ($, e) => {
    prompts.push(String(e.prompt))
    return { value: { isAnswered: true, text: REPLY, usage: {} } } as never
  })
  const r = await $.command.run({ command: 'flow', args: '', origin: { kind: 'composer' } } as never)
  expect(JSON.stringify(r)).toContain('reflect 품질 개선')
  expect(prompts[0]).toContain('14개를 거절할까요?')

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'flow-band', surface, component: 'AbovePrompt', props: PROPS(3) })
    expect(await ui.find({ type: 'Text', text: /📍 agent-memory/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '✓ 엔진 → ✓ recall → ● 기준 수정 → ○ 윈도우 설치' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /내 답 필요: 제안 14개/ })).toBeDefined()
    await ui.unmount()
    // Claude가 작업 중이면 "내 답 필요"는 숨김, 한 줄만 허용되면 흐름만
    const busy = await $.ui.mount({ plugin: 'flow-band', surface, component: 'AbovePrompt', props: PROPS(1, true) })
    expect(await busy.find({ type: 'Text', text: /내 답 필요/ })).toBeUndefined()
    expect(await busy.find({ type: 'Text', text: /📍/ })).toBeUndefined()
    expect(await busy.find({ type: 'Text', text: /● 기준 수정/ })).toBeDefined()
    await busy.unmount()
  }
})
