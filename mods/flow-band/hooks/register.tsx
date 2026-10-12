import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { Flow } from '../types'
import { buildPrompt, parseFlow, projectOf, stepsLine, storeKey, transcriptDigest } from './flow.ts'

const flow = atom({ plugin: 'flow-band', key: 'flow' } as const, null as Flow | null)
const hidden = atom({ plugin: 'flow-band', key: 'hidden' } as const, false)
const toolsSince = atom({ plugin: 'flow-band', key: 'toolsSince' } as const, 0)
const turnsSince = atom({ plugin: 'flow-band', key: 'turnsSince' } as const, 0)
const updating = atom({ plugin: 'flow-band', key: 'updating' } as const, false)
// 도구를 안 쓴 대화 턴도 이 횟수마다 한 번은 갱신 (waiting 반영)
const REFRESH_EVERY_TURNS = 2

// 대화 요약 → 흐름 갱신 → 폴더별로 저장 (세션이 바뀌어도 유지)
async function refresh($: EngineInterface, options: PluginOptions): Promise<void> {
  if (await read($, updating)) return
  await update($, updating, () => true)
  try {
    const cwd = await $.session.cwd()
    const messages = await $.session.messages()
    if (!Array.isArray(messages) || messages.length === 0) return
    const prev = await read($, flow)
    const r = await $.model.complete({
      model: String(options.model || 'haiku'),
      prompt: buildPrompt(transcriptDigest(messages), prev && prev.project === projectOf(cwd) ? prev : null),
      maxTokens: 800,
      timeoutMs: 30_000,
    })
    if (!r.isAnswered) return
    const next = parseFlow(r.text, projectOf(cwd), Date.now())
    if (!next) return
    await update($, flow, () => next)
    await $.store.set(storeKey(cwd), next)
  } finally {
    await update($, toolsSince, () => 0)
    await update($, turnsSince, () => 0)
    await update($, updating, () => false)
  }
}

export const register: Register = (on, options) => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'flow', description: '작업 흐름 band 지금 갱신' })
    await $.command.register({ name: 'flow-toggle', description: '작업 흐름 band 보이기/숨기기' })
    // 같은 폴더의 지난 흐름을 바로 보여줌
    const saved = (await $.store.get(storeKey(await $.session.cwd()))) as Flow | undefined
    if (saved && Array.isArray(saved.steps)) await update($, flow, () => saved)
    return next(e)
  })

  on('command.run', { command: 'flow' }, async $ => {
    await refresh($, options)
    const f = await read($, flow)
    return { text: f ? `흐름 갱신: ${f.goal}` : '갱신할 대화가 아직 없어요.' }
  })

  on('command.run', { command: 'flow-toggle' }, async $ => {
    const now = await update($, hidden, h => !h)
    return { text: now ? '작업 흐름 band를 숨겼어요. /flow-toggle로 다시 보기' : '작업 흐름 band를 다시 보여줘요.' }
  })

  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if (!e.agentId) await update($, toolsSince, n => n + 1).catch(() => {})
    return ran
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    // 메인 대화의 정상 종료만, 엔진 내부 claude -p 제외
    if (e.agentId || e.reason !== 'answer' || (await $.env.get('AMEM_INTERNAL')) === '1') return done
    const turns = await update($, turnsSince, n => n + 1)
    const tools = await read($, toolsSince)
    if (tools > 0 || turns >= REFRESH_EVERY_TURNS || !(await read($, flow))) {
      // 턴 종료를 늦추지 않게 백그라운드로
      void refresh($, options).catch(() => {})
    }
    return done
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const f = await read($, flow)
    if (!f || e.props.hasSurvey || (await read($, hidden)) || e.props.maxRows < 1) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const width = Math.max(20, e.props.bodyColumns - 2)
    const isUpdating = await read($, updating)
    const rows = e.props.maxRows

    return (
      <Box flexDirection="column">
        {rows >= 2 && (
          <Text>
            <Text bold>📍 {f.project}</Text>
            <Text dimColor>{f.goal ? ` · ${f.goal}` : ''}{isUpdating ? ' · 갱신 중…' : ''}</Text>
          </Text>
        )}
        <Text>{stepsLine(f.steps, width)}</Text>
        {rows >= 3 && f.waiting && !e.props.isWorking && <Text color="yellow">⏸ 내 답 필요: {f.waiting}</Text>}
      </Box>
    )
  })
}
