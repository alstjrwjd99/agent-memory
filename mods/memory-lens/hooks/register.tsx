import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { Health, LastRecall, PendingItem, RecallHit, Scope, StoreHealth } from '../types'
import { changeLine, classifyPath, clip, countsLine, pendingItems, resolvePaths, shouldRecall } from './parse.ts'

const PANE = 'memory-lens'
const TITLE = '🧠 Memory'
const stores = atom({ plugin: 'memory-lens', key: 'stores' } as const, [] as StoreHealth[])
const pending = atom({ plugin: 'memory-lens', key: 'pending' } as const, [] as PendingItem[])
const busy = atom({ plugin: 'memory-lens', key: 'busy' } as const, null as string | null)
const message = atom({ plugin: 'memory-lens', key: 'message' } as const, null as string | null)
const saved = atom({ plugin: 'memory-lens', key: 'saved' } as const, [] as { at: number; name: string }[])
const turns = atom({ plugin: 'memory-lens', key: 'turns' } as const, 0)
const lastRecall = atom({ plugin: 'memory-lens', key: 'recall' } as const, null as LastRecall | null)
const loadedAt = atom({ plugin: 'memory-lens', key: 'loadedAt' } as const, 0)
const KIND_LABEL: Record<string, string> = { opinion: '판단', procedure: '절차', observation: '관찰', experience: '경험', world: '사실' }
const RELOAD_EVERY_MS = 30_000

async function paths($: EngineInterface, options: PluginOptions) {
  const home = (await $.env.get('HOME')) ?? (await $.env.get('USERPROFILE')) ?? ''
  return resolvePaths(home, String(options.store ?? ''), String(options.engineDir ?? ''), String(options.workStore ?? ''))
}

// personal/work store의 health + 승인 대기 제안을 파일에서 다시 읽는다 (엔진 실행 없음)
async function reload($: EngineInterface, options: PluginOptions): Promise<void> {
  const p = await paths($, options)
  const machine = String(options.machine || 'mac')
  const found: StoreHealth[] = []
  const items: PendingItem[] = []
  for (const [scope, root] of [['personal', p.store], ['work', p.workStore]] as [Scope, string][]) {
    if (!(await $.fs.exists(root))) continue
    const hp = `${root}/.amem/health-${machine}.json`
    const health = (await $.fs.exists(hp)) ? (JSON.parse(String(await $.fs.read(hp))) as Health) : null
    found.push({ scope, health })
    const dir = `${root}/proposals`
    if (!(await $.fs.exists(dir))) continue
    const files: string[] = []
    for (const f of await $.fs.list(dir)) {
      if (f.kind === 'file' && f.name.endsWith('.json')) files.push(String(await $.fs.read(`${dir}/${f.name}`)))
    }
    items.push(...pendingItems(files, scope))
  }
  await update($, stores, () => found)
  await update($, pending, () => items)
  await update($, loadedAt, () => Date.now())
}

// 엔진 실행 경로: venv의 amem이 있으면 직접, 없으면 uv run
async function amemArgv($: EngineInterface, engineDir: string): Promise<string[]> {
  for (const candidate of [`${engineDir}/.venv/bin/amem`, `${engineDir}/.venv/Scripts/amem.exe`]) {
    if (await $.fs.exists(candidate)) return [candidate]
  }
  return ['uv', 'run', '--project', engineDir, 'amem']
}

// amem CLI 실행 후 새로 읽기. 실행 중엔 버튼을 잠근다
async function amem($: EngineInterface, options: PluginOptions, label: string, scope: Scope, args: string[]): Promise<void> {
  if (await read($, busy)) return
  await update($, busy, () => label)
  try {
    const { engineDir } = await paths($, options)
    const exe = await amemArgv($, engineDir)
    const r = await $.process.run([...exe, '--store', scope, ...args], { timeoutMs: 600_000 })
    const last = (r.exitCode === 0 ? r.stdout : r.stderr).trim().split('\n').pop() ?? ''
    await update($, message, () => `${r.exitCode === 0 ? '✓' : '✗'} ${label}: ${clip(last, 60)}`)
  } catch (err) {
    await update($, message, () => `✗ ${label}: ${String(err).slice(0, 60)}`)
  } finally {
    await update($, busy, () => null)
    await reload($, options)
  }
}

// 엔진 recall 호출 (LLM 없음). 실패하면 null → 프롬프트는 그대로 진행
async function runRecall($: EngineInterface, options: PluginOptions, query: string): Promise<{ context: string; scope: string; hits: RecallHit[] } | null> {
  const { engineDir } = await paths($, options)
  const cwd = await $.session.cwd()
  const exe = await amemArgv($, engineDir)
  const r = await $.process.run([...exe, 'recall', query, '--cwd', cwd, '--json'], { timeoutMs: 5_000 })
  if (r.exitCode !== 0) return null
  return JSON.parse(r.stdout) as { context: string; scope: string; hits: RecallHit[] }
}

export const register: Register = (on, options) => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'memory-lens', description: '기억 현황 pane 열기' })
    void reload($, options)
    void $.ui.open({ id: PANE, title: TITLE })
    // 터미널에서 직접 amem을 돌려도 pane이 따라오도록 주기적으로 파일을 다시 읽음
    $.clock.every(RELOAD_EVERY_MS, () => void reload($, options))
    return next(e)
  })

  on('command.run', { command: 'memory-lens' }, async $ => {
    await reload($, options)
    const { isPlaced } = await $.ui.open({ id: PANE, title: TITLE })
    return { text: isPlaced ? '기억 현황 pane을 열었어요.' : '터미널 폭이 좁아 pane을 못 띄웠어요. 창을 넓혀주세요.' }
  })

  // recall: 사용자가 보낸 프롬프트에 관련 기억을 보이지 않는 context로 붙인다
  on('prompt.submit', async ($, e, next) => {
    if (options.recall === false || !shouldRecall(e.text)) return next(e)
    // 엔진 자신이 띄운 claude -p에는 붙이지 않음 (기억이 기억 추출을 오염시키지 않게)
    if ((await $.env.get('AMEM_INTERNAL')) === '1') return next(e)
    let found: Awaited<ReturnType<typeof runRecall>> = null
    try {
      found = await runRecall($, options, e.text)
    } catch {}
    if (!found || found.hits.length === 0 || !found.context) {
      await update($, lastRecall, () => ({ at: Date.now(), query: e.text, scope: found?.scope ?? '-', hits: [] }))
      return next(e)
    }
    await update($, lastRecall, () => ({ at: Date.now(), query: e.text, scope: found.scope, hits: found.hits }))
    $.ui.status(`🧠 recall ${found.hits.length}개`)
    return next({ ...e, context: [...(e.context ?? []), found.context] })
  }).catch(($, e, next) => next(e))

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
    const all = await read($, stores)
    const items = await read($, pending)
    const working = await read($, busy)
    const msg = await read($, message)
    const turnCount = await read($, turns)
    const rc = await read($, lastRecall)
    const at = await read($, loadedAt)
    const width = Math.max(24, (e.viewport?.columns ?? 44) - 14)
    const changes = all
      .flatMap(s => (s.health?.recent_changes ?? []).map(c => ({ ...c, scope: s.scope })))
      .sort((a, b) => (a.at < b.at ? 1 : -1))
      .slice(0, 5)

    return (
      <Box flexDirection="column">
        <Text bold>Memory Health</Text>
        {all.length === 0 && <Text dimColor>store 없음: 설정의 store 경로 확인</Text>}
        {all.map(s => (
          <Box key={`st-${s.scope}`} flexDirection="column">
            <Text>
              <Text bold>{s.scope}</Text>
              {s.health ? `  대기 ${s.health.pending_proposals} · 충돌 ${s.health.conflicts.length}` : '  (health 없음)'}
            </Text>
            {s.health && <Text dimColor>  {countsLine(s.health.counts)}</Text>}
          </Box>
        ))}

        {changes.length > 0 && <Text bold>─ Recent Reflection ─</Text>}
        {changes.map(ch => (
          <Text key={`ch-${ch.scope}-${ch.id}`}>{changeLine(ch, width - 12)}</Text>
        ))}

        <Text bold>─ 이번에 꺼낸 기억 {rc ? `(${rc.scope})` : ''} ─</Text>
        {!rc && <Text dimColor>아직 없음 (프롬프트를 보내면 표시)</Text>}
        {rc && rc.hits.length === 0 && <Text dimColor>관련 기억 없음: "{clip(rc.query, width - 18)}"</Text>}
        {rc?.hits.map(h => (
          <Box key={`rc-${h.id}`} flexDirection="column">
            <Text>
              {KIND_LABEL[h.kind] ?? h.kind} {clip(h.label, width - 6)}
            </Text>
            <Text dimColor>  {clip(`${h.score} · ${h.why.join(', ')}`, width)}</Text>
          </Box>
        ))}

        <Text bold>─ 승인 대기 {items.length} ─</Text>
        {items.length === 0 && <Text dimColor>없음</Text>}
        {items.slice(0, 6).map(it => (
          <Box key={`it-${it.scope}-${it.pid}-${it.n}`} flexDirection="column">
            <Text>
              <Text dimColor>{it.scope === 'work' ? 'W ' : 'P '}</Text>
              {clip(it.text, width - 2)}
            </Text>
            <Box flexDirection="row">
              <Button key={`ok-${it.scope}-${it.pid}-${it.n}`} label="승인" onPress={() => amem($, options, `#${it.n} 승인`, it.scope, ['apply', it.pid, '--only', String(it.n)])} />
              <Text> </Text>
              <Button key={`no-${it.scope}-${it.pid}-${it.n}`} label="거절" onPress={() => amem($, options, `#${it.n} 거절`, it.scope, ['reject', it.pid, '--only', String(it.n)])} />
            </Box>
          </Box>
        ))}
        {items.length > 6 && <Text dimColor>…외 {items.length - 6}개 (amem review)</Text>}

        <Box flexDirection="row">
          <Button key="refresh" label="새로고침" onPress={() => reload($, options)} />
          <Text> </Text>
          <Button key="run" label="기억 정리(LLM)" onPress={() => amem($, options, '기억 정리', 'personal', ['run'])} />
        </Box>
        {working && <Text color="yellow">⏳ {working} 실행 중…</Text>}
        {!working && msg && <Text dimColor>{msg}</Text>}
        <Text dimColor>
          이번 세션 {turnCount}턴 · 갱신 {at ? new Date(at).toTimeString().slice(0, 8) : '-'}
        </Text>
      </Box>
    )
  })
}
