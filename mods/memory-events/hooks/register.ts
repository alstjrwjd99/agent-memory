import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { MemoryEvent } from '../types'
import { correctionOf, eventFile, isoLocal, scopeOf, targetOf, toJsonl } from './core.ts'

const buffer = atom({ plugin: 'memory-events', key: 'buffer' } as const, null)

const opt = (options: PluginOptions, k: string): string => String(options[k] ?? '')

// 이벤트 하나를 세션 버퍼에 추가 (모듈 변수 대신 $.state: 리로드에도 유지)
async function push($: EngineInterface, ev: Omit<MemoryEvent, 'ts'>): Promise<void> {
  // 엔진(amem)이 claude -p로 부른 세션은 기록하지 않는다
  if ((await $.env.get('AMEM_INTERNAL')) === '1') return
  const sessionId = await $.session.id()
  await update($, buffer, b => {
    const base = b && b.sessionId === sessionId ? b : { sessionId, startedAt: isoLocal(new Date()), events: [] }
    return { ...base, events: [...base.events, { ts: isoLocal(new Date()), ...ev }] }
  })
}

// 세션 파일 전체를 다시 쓴다 (fs.write는 append가 없음, 세션별 파일이라 다른 세션과 충돌 없음)
async function flush($: EngineInterface, options: PluginOptions): Promise<void> {
  const b = await read($, buffer)
  if (!b || b.events.length === 0) return
  const scope = scopeOf(await $.session.cwd(), opt(options, 'workPaths'), opt(options, 'defaultScope'))
  const store = scope === 'work' ? opt(options, 'workStore') : opt(options, 'personalStore')
  if (!store) {
    $.ui.status(`memory-events: ${scope} store 경로 미설정`)
    return
  }
  const path = eventFile(store, opt(options, 'machine') || 'unknown', b.startedAt, b.sessionId)
  // 첫 flush 때 기존 파일 내용을 한 번 읽어 앞에 붙인다 (덮어쓰기로 이전 이벤트가 사라지지 않게)
  let prior = b.prior ?? ''
  if (!b.priorLoaded) {
    prior = (await $.fs.exists(path)) ? String(await $.fs.read(path)) : ''
    await update($, buffer, cur => (cur ? { ...cur, prior, priorLoaded: true } : cur))
  }
  await $.fs.write(path, prior + toJsonl(b.events))
}

export const register: Register = (on, options) => {
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    try {
      const cwd = await $.session.cwd()
      const ok = ran.deny === undefined && ran.isError !== true
      await push($, { kind: 'tool', name: e.tool, target: targetOf(e.tool, e as unknown as Record<string, unknown>, cwd), ok })
    } catch {}
    return ran
  }).catch(($, e, next) => next(e))

  on('prompt.submit', async ($, e, next) => {
    const hit = correctionOf(e.text)
    if (hit) await push($, { kind: 'correction', name: hit }).catch(() => {})
    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    try {
      await push($, { kind: 'turn', name: e.reason })
      await flush($, options)
    } catch {}
    return next(e)
  })
}
