import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { Health, PendingItem } from '../types'
import { changeLine, classifyPath, clip, pendingItems, resolvePaths } from './parse.ts'

const PANE = 'memory-lens'
const TITLE = '🧠 Memory'
const health = atom({ plugin: 'memory-lens', key: 'health' } as const, null as Health | null)
const pending = atom({ plugin: 'memory-lens', key: 'pending' } as const, [] as PendingItem[])
const busy = atom({ plugin: 'memory-lens', key: 'busy' } as const, null as string | null)
const message = atom({ plugin: 'memory-lens', key: 'message' } as const, null as string | null)
const saved = atom({ plugin: 'memory-lens', key: 'saved' } as const, [] as { at: number; name: string }[])
const turns = atom({ plugin: 'memory-lens', key: 'turns' } as const, 0)

async function paths($: EngineInterface, options: PluginOptions): Promise<{ store: string; engineDir: string }> {
  const home = (await $.env.get('HOME')) ?? (await $.env.get('USERPROFILE')) ?? ''
  return resolvePaths(home, String(options.store ?? ''), String(options.engineDir ?? ''))
}

// health JSON + 승인 대기 제안을 파일에서 다시 읽는다 (LLM/엔진 실행 없음)
async function reload($: EngineInterface, options: PluginOptions): Promise<void> {
  const { store } = await paths($, options)
  const machine = String(options.machine || 'mac')
  const hp = `${store}/.amem/health-${machine}.json`
  const h = (await $.fs.exists(hp)) ? (JSON.parse(String(await $.fs.read(hp))) as Health) : null
  const dir = `${store}/proposals`
  const files: string[] = []
  if (await $.fs.exists(dir)) {
    for (const f of await $.fs.list(dir)) {
      if (f.kind === 'file' && f.name.endsWith('.json')) files.push(String(await $.fs.read(`${dir}/${f.name}`)))
    }
  }
  await update($, health, () => h)
  await update($, pending, () => pendingItems(files))
}

// amem CLI 실행 후 새로 읽기. 실행 중엔 버튼을 잠근다
async function amem($: EngineInterface, options: PluginOptions, label: string, args: string[]): Promise<void> {
  if (await read($, busy)) return
  await update($, busy, () => label)
  try {
    const { engineDir } = await paths($, options)
    const scope = String(options.scope || 'personal')
    const r = await $.process.run(['uv', 'run', '--project', engineDir, 'amem', '--store', scope, ...args], {
      timeoutMs: 600_000,
      env: { AMEM_INTERNAL: '1' },
    })
    const last = (r.exitCode === 0 ? r.stdout : r.stderr).trim().split('\n').pop() ?? ''
    await update($, message, () => `${r.exitCode === 0 ? '✓' : '✗'} ${label}: ${clip(last, 60)}`)
    if (args[0] !== 'health') {
      await $.process.run(['uv', 'run', '--project', engineDir, 'amem', '--store', scope, 'health'], { timeoutMs: 60_000 })
    }
  } catch (err) {
    await update($, message, () => `✗ ${label}: ${String(err).slice(0, 60)}`)
  } finally {
    await update($, busy, () => null)
    await reload($, options)
  }
}

export const register: Register = (on, options) => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'memory-lens', description: '기억 현황 pane 열기' })
    void reload($, options)
    void $.ui.open({ id: PANE, title: TITLE })
    return next(e)
  })

  on('command.run', { command: 'memory-lens' }, async $ => {
    await reload($, options)
    const { isPlaced } = await $.ui.open({ id: PANE, title: TITLE })
    return { text: isPlaced ? 'memory-lens: 기억 현황 pane을 열었어요.' : '터미널 폭이 좁아 pane을 못 띄웠어요. 창을 넓혀주세요.' }
  })

  on('turn.complete', async ($, e, next) => {
    await update($, turns, n => n + 1)
    void reload($, options)
    return next(e)
  })

  // Claude가 Claude Code 메모리/스킬을 쓰면 알림
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if (e.tool !== 'Write' && e.tool !== 'Edit') return ran
    const hit = classifyPath(e.file_path)
    if (!hit || ran.deny !== undefined || ran.isError === true) return ran
    try {
      const label = hit.kind === 'skill' ? `skill: ${hit.name}` : hit.name
      $.ui.toast(`🧠 기억 저장: ${label}`)
      await update($, saved, list => [...list, { at: Date.now(), name: label }].slice(-20))
    } catch {}
    return ran
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const h = await read($, health)
    const items = await read($, pending)
    const working = await read($, busy)
    const msg = await read($, message)
    const turnCount = await read($, turns)
    const width = Math.max(24, (e.viewport?.columns ?? 44) - 14)
    const c = h?.counts

    return (
      <Box flexDirection="column">
        <Text bold>Memory Health {h ? `(${h.machine})` : ''}</Text>
        {!h && <Text dimColor>health 없음: [새로고침]을 눌러주세요</Text>}
        {c && <Text>World {c.world} · Experience {c.experience}</Text>}
        {c && <Text>Observation {c.observation} · Opinion {c.opinion} · Procedure {c.procedure}</Text>}
        {h && <Text>오늘 +{h.new_today} · 갱신 {h.updated_today} · 충돌 {h.conflicts.length}</Text>}
        {h && (
          <Text dimColor>
            대기: 세션 {h.pending_sessions} · episode {h.fresh_episodes} · 이번 세션 {turnCount}턴
          </Text>
        )}

        {h && h.recent_changes.length > 0 && <Text bold>─ Recent Reflection ─</Text>}
        {h?.recent_changes.map(ch => (
          <Text key={`ch-${ch.id}`}>{changeLine(ch, width - 12)}</Text>
        ))}

        <Text bold>─ 승인 대기 {items.length} ─</Text>
        {items.length === 0 && <Text dimColor>없음</Text>}
        {items.slice(0, 6).map(it => (
          <Box key={`it-${it.pid}-${it.n}`} flexDirection="column">
            <Text>{clip(it.text, width)}</Text>
            <Box flexDirection="row">
              <Button key={`ok-${it.pid}-${it.n}`} label="승인" onPress={() => amem($, options, `#${it.n} 승인`, ['apply', it.pid, '--only', String(it.n)])} />
              <Text> </Text>
              <Button key={`no-${it.pid}-${it.n}`} label="거절" onPress={() => amem($, options, `#${it.n} 거절`, ['reject', it.pid, '--only', String(it.n)])} />
            </Box>
          </Box>
        ))}
        {items.length > 6 && <Text dimColor>…외 {items.length - 6}개 (amem review)</Text>}

        <Box flexDirection="row">
          <Button key="refresh" label="새로고침" onPress={() => amem($, options, '새로고침', ['health'])} />
          <Text> </Text>
          <Button key="run" label="기억 정리(LLM)" onPress={() => amem($, options, '기억 정리', ['run'])} />
        </Box>
        {working && <Text color="yellow">⏳ {working} 실행 중…</Text>}
        {!working && msg && <Text dimColor>{msg}</Text>}
      </Box>
    )
  })
}
