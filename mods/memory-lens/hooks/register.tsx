import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { Flow, Health, LastRecall, OtherFlow, PendingItem, RecallHit, Scope, StoreHealth } from '../types'
import { ago, buildPrompt, otherFlows, parseFlow, projectOf, storeKey, transcriptDigest, verticalSteps } from './flow.ts'
import { changeLine, classifyPath, clip, countsLine, pendingItems, resolvePaths, shouldRecall } from './parse.ts'

const PANE = 'memory-lens'
const TITLE = '🧭 작업 흐름'
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
const flow = atom({ plugin: 'memory-lens', key: 'flow' } as const, null as Flow | null)
const flowUpdating = atom({ plugin: 'memory-lens', key: 'flowUpdating' } as const, false)
const toolsSince = atom({ plugin: 'memory-lens', key: 'toolsSince' } as const, 0)
const turnsSinceFlow = atom({ plugin: 'memory-lens', key: 'turnsSinceFlow' } as const, 0)
// 도구를 안 쓴 대화 턴도 이 횟수마다 한 번은 흐름 갱신 (내 답 필요 반영)
const FLOW_EVERY_TURNS = 2
const MARK = { done: '✓', now: '●', next: '○' } as const
const others = atom({ plugin: 'memory-lens', key: 'others' } as const, [] as OtherFlow[])
// 기억 상세(Health, 승인 버튼) 펼침 여부, 마지막으로 확인한 승인 대기 수 (새로 생겼을 때만 알림)
const expanded = atom({ plugin: 'memory-lens', key: 'expanded' } as const, false)
const seenPending = atom({ plugin: 'memory-lens', key: 'seenPending' } as const, 0)

// 다른 폴더(작업)들의 흐름: 같은 PC의 다른 세션이 저장한 것도 포함
async function loadOthers($: EngineInterface): Promise<void> {
  const cwd = await $.session.cwd()
  const flows: Flow[] = []
  for (const key of await $.store.keys()) {
    if (!key.startsWith('flow:') || key === storeKey(cwd)) continue
    const f = (await $.store.get(key)) as Flow | undefined
    if (f) flows.push(f)
  }
  await update($, others, () => otherFlows(flows, projectOf(cwd)))
}

// 대화 요약 → 흐름 갱신 → 폴더별 저장 (세션이 바뀌어도 유지). haiku로 최근 40개 메시지만
async function refreshFlow($: EngineInterface, options: PluginOptions): Promise<void> {
  if (await read($, flowUpdating)) return
  await update($, flowUpdating, () => true)
  try {
    const cwd = await $.session.cwd()
    const messages = await $.session.messages()
    if (!Array.isArray(messages) || messages.length === 0) return
    const prev = await read($, flow)
    const r = await $.model.complete({
      model: String(options.flowModel || 'haiku'),
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
    await update($, turnsSinceFlow, () => 0)
    await update($, flowUpdating, () => false)
  }
}

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
  await loadOthers($).catch(() => {})
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
    await $.command.register({ name: 'flow', description: '작업 흐름 지금 갱신' })
    // 같은 폴더의 지난 흐름을 바로 보여줌
    const saved = (await $.store.get(storeKey(await $.session.cwd()))) as Flow | undefined
    if (saved && Array.isArray(saved.steps)) await update($, flow, () => ({ ...saved, detail: saved.detail ?? null }))
    void reload($, options)
    void $.ui.open({ id: PANE, title: TITLE })
    // 터미널에서 직접 amem을 돌려도 pane이 따라오도록 주기적으로 파일을 다시 읽음
    $.clock.every(RELOAD_EVERY_MS, () => void reload($, options))
    return next(e)
  })

  on('command.run', { command: 'memory-lens' }, async $ => {
    await reload($, options)
    await update($, expanded, () => true)
    const { isPlaced } = await $.ui.open({ id: PANE, title: TITLE })
    return { text: isPlaced ? '기억 현황 pane을 열었어요.' : '터미널 폭이 좁아 pane을 못 띄웠어요. 창을 넓혀주세요.' }
  })

  on('command.run', { command: 'flow' }, async $ => {
    await refreshFlow($, options)
    const f = await read($, flow)
    void $.ui.open({ id: PANE, title: TITLE })
    return { text: f ? `흐름 갱신: ${f.goal}${f.detail ? ` (지금: ${f.detail})` : ''}` : '갱신할 대화가 아직 없어요.' }
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
    const done = await next(e)
    // 메인 대화의 정상 종료만 (서브에이전트, 엔진 내부 claude -p 제외)
    if (e.agentId || (await $.env.get('AMEM_INTERNAL')) === '1') return done
    await update($, turns, n => n + 1)
    void reload($, options)
    if (e.reason === 'answer' && options.flow !== false) {
      const t = await update($, turnsSinceFlow, n => n + 1)
      if ((await read($, toolsSince)) > 0 || t >= FLOW_EVERY_TURNS || !(await read($, flow))) {
        // 턴 종료를 늦추지 않게 백그라운드로
        void refreshFlow($, options).catch(() => {})
      }
    }
    return done
  })

  // Claude가 Claude Code 메모리/스킬을 쓰면 알림
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if (!e.agentId) await update($, toolsSince, n => n + 1).catch(() => {})
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
    const rc = await read($, lastRecall)
    const f = await read($, flow)
    const fUpdating = await read($, flowUpdating)
    const rest = await read($, others)
    const isOpen = await read($, expanded)
    const seen = await read($, seenPending)
    const width = Math.max(24, (e.viewport?.columns ?? 44) - 6)
    const now = Date.now()
    const recallHits = rc && rc.hits.length > 0 ? rc.hits : []
    const newPending = Math.max(0, items.length - seen)
    // 기억 영역은 쓰였거나(recall) 새 제안이 생겼거나 직접 펼쳤을 때만
    const showMemory = isOpen || recallHits.length > 0 || newPending > 0
    const changes = all
      .flatMap(st => (st.health?.recent_changes ?? []).map(c => ({ ...c, scope: st.scope })))
      .sort((x, y) => (x.at < y.at ? 1 : -1))
      .slice(0, 3)

    return (
      <Box flexDirection="column">
        {/* ── 주인공: 지금 작업 흐름 ── */}
        {!f && <Text dimColor>흐름 없음: 대화가 쌓이면 자동으로 정리돼요 (/flow)</Text>}
        {f && (
          <Box key="flow" flexDirection="column">
            <Text>
              <Text bold>📍 {f.project}</Text>
              <Text dimColor>{fUpdating ? ' · 갱신 중…' : ` · ${ago(f.at, now)} 전 갱신`}</Text>
            </Text>
            {f.goal && <Text dimColor>목표: {clip(f.goal, width)}</Text>}
            {verticalSteps(f.steps).map((row, i, rows) =>
              row.kind === 'folded' ? (
                <Text key="fold" dimColor> ✓ … {row.count}개 완료</Text>
              ) : (
                <Box key={`step-${i}`} flexDirection="column">
                  <Text bold={row.status === 'now'} dimColor={row.status === 'done'} color={row.status === 'now' ? 'cyan' : undefined}>
                    {' '}{MARK[row.status]} {clip(row.label, width - 4)}
                  </Text>
                  {row.status === 'now' && f.detail && <Text color="cyan"> │  └ 지금: {clip(f.detail, width - 12)}</Text>}
                  {i < rows.length - 1 && <Text dimColor> │</Text>}
                </Box>
              ),
            )}
            {f.waiting && !working && <Text color="yellow">⏸ 내 답 필요: {clip(f.waiting, width - 10)}</Text>}
          </Box>
        )}

        {/* ── 다른 작업: 여러 일을 오갈 때 돌아갈 곳 ── */}
        {rest.length > 0 && <Text bold>─ 다른 작업 ─</Text>}
        {rest.map(o => (
          <Text key={`other-${o.project}`}>
            <Text bold>{clip(o.project, 16)}</Text>
            {o.waiting ? <Text color="yellow"> ⏸ {clip(o.waiting, width - 22)}</Text> : <Text> ● {clip(o.now ?? '-', width - 22)}</Text>}
            <Text dimColor> {ago(o.at, now)}</Text>
          </Text>
        ))}

        {/* ── 조연: 기억 (쓰일 때/새로 생길 때만) ── */}
        {showMemory && <Text dimColor>{'─'.repeat(Math.min(width, 36))}</Text>}
        {recallHits.length > 0 && (
          <Box key="recall" flexDirection="column">
            <Text bold>🧠 방금 꺼낸 기억</Text>
            {recallHits.slice(0, 3).map(h => (
              <Text key={`rc-${h.id}`}>
                <Text dimColor> {KIND_LABEL[h.kind] ?? h.kind} </Text>
                {clip(h.label, width - 8)}
              </Text>
            ))}
          </Box>
        )}
        {newPending > 0 && !isOpen && (
          <Box key="new" flexDirection="row">
            <Text color="magenta">✨ 새 기억 후보 {newPending}개 </Text>
            <Button key="open" label="보기" onPress={() => update($, expanded, () => true)} />
            <Text> </Text>
            <Button key="later" label="나중에" onPress={() => update($, seenPending, () => items.length)} />
          </Box>
        )}
        {isOpen && (
          <Box key="detail" flexDirection="column">
            {all.map(st => (
              <Text key={`st-${st.scope}`}>
                <Text bold>{st.scope}</Text>
                <Text dimColor> {st.health ? countsLine(st.health.counts) : '(health 없음)'}</Text>
              </Text>
            ))}
            {changes.map(ch => (
              <Text key={`ch-${ch.scope}-${ch.id}`} dimColor>{changeLine(ch, width - 12)}</Text>
            ))}
            <Text bold>승인 대기 {items.length}</Text>
            {items.slice(0, 5).map(it => (
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
            {items.length > 5 && <Text dimColor>…외 {items.length - 5}개 (amem review)</Text>}
            <Box flexDirection="row">
              <Button key="refresh" label="새로고침" onPress={() => reload($, options)} />
              <Text> </Text>
              <Button key="close" label="접기" onPress={async () => { await update($, seenPending, () => items.length); await update($, expanded, () => false) }} />
            </Box>
            {working && <Text color="yellow">⏳ {working} 실행 중…</Text>}
            {!working && msg && <Text dimColor>{msg}</Text>}
          </Box>
        )}
      </Box>
    )
  })
}
