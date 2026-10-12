import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { MemorySnapshot, SavedMemory } from '../types'
import { classifyPath, memoryType, paths } from './parse.ts'

const PANE = 'memory-lens'
const snapshot = atom({ plugin: 'memory-lens', key: 'snapshot' } as const, null as MemorySnapshot | null)
const saved = atom({ plugin: 'memory-lens', key: 'saved' } as const, [] as SavedMemory[])
const turns = atom({ plugin: 'memory-lens', key: 'turns' } as const, 0)

// 메모리 폴더와 스킬 폴더를 훑어 스냅샷 갱신
async function scan($: EngineInterface): Promise<void> {
  const home = (await $.env.get('HOME')) ?? (await $.env.get('USERPROFILE')) ?? ''
  const { memoryDir, skillsDir } = paths(home)
  const byType: Record<string, number> = {}
  const files = (await $.fs.list(memoryDir)).filter(f => f.kind === 'file' && f.name.endsWith('.md') && f.name !== 'MEMORY.md')
  for (const f of files) {
    const text = await $.fs.read(`${memoryDir}/${f.name}`)
    const type = memoryType(f.name, typeof text === 'string' ? text : '')
    byType[type] = (byType[type] ?? 0) + 1
  }
  const skills = (await $.fs.list(skillsDir)).filter(s => s.kind !== 'file' && !s.name.startsWith('.')).length
  await update($, snapshot, () => ({ byType, skills, scannedAt: Date.now() }))
}

const hhmm = (ms: number) => new Date(ms).toTimeString().slice(0, 5)

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'memory-lens', description: '기억 현황 pane 열기' })
    void $.ui.open({ id: PANE, title: '🧠 Memory' })
    void scan($)
    return next(e)
  })

  on('command.run', { command: 'memory-lens' }, async $ => {
    await scan($)
    const { isPlaced } = await $.ui.open({ id: PANE, title: '🧠 Memory' })
    return { text: isPlaced ? '기억 현황 pane을 열었어요.' : '터미널 폭이 좁아 pane을 못 띄웠어요. 창을 넓혀주세요.' }
  })

  on('turn.complete', async ($, e, next) => {
    await update($, turns, n => n + 1)
    return next(e)
  })

  // Write/Edit가 기억·스킬 파일을 건드리면 알림 + 기록 + 재스캔
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if (e.tool !== 'Write' && e.tool !== 'Edit') return ran
    const hit = classifyPath(e.file_path)
    if (!hit || ran.deny !== undefined || ran.isError === true) return ran
    // 알림/기록이 실패해도 도구 결과는 그대로 돌려준다
    try {
      const label = hit.kind === 'skill' ? `skill: ${hit.name}` : hit.name
      $.ui.toast(`🧠 기억 저장: ${label}`)
      await update($, saved, list => [...list, { at: Date.now(), kind: hit.kind, name: label }].slice(-20))
      void scan($)
    } catch {}
    return ran
  }).catch(($, e, next) =>
    // 관찰용 훅이라 실패해도 막지 않고 통과
    next(e),
  )

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const snap = await read($, snapshot)
    const list = await read($, saved)
    const turnCount = await read($, turns)
    const by = snap?.byType ?? {}
    const semantic = (by.project ?? 0) + (by.reference ?? 0) + (by.user ?? 0)
    const rest = Object.entries(by).filter(([k]) => !['project', 'reference', 'user', 'feedback'].includes(k))

    return (
      <Box flexDirection="column">
        <Text bold>Working</Text>
        <Text>  이번 세션 {turnCount}턴</Text>
        <Text bold>Episodic</Text>
        <Text dimColor>  (아직 미수집)</Text>
        <Text bold>Semantic  {semantic}</Text>
        <Text>  project {by.project ?? 0} · ref {by.reference ?? 0} · user {by.user ?? 0}</Text>
        <Text bold>Procedural</Text>
        <Text>  스킬 {snap?.skills ?? '-'} · feedback {by.feedback ?? 0}</Text>
        {rest.length > 0 && <Text dimColor>  기타 {rest.map(([k, v]) => `${k} ${v}`).join(' · ')}</Text>}
        <Text bold>─ 이번 세션 저장 ─</Text>
        {list.length === 0 && <Text dimColor>  아직 없음</Text>}
        {list.slice(-8).reverse().map(s => (
          <Text>  {hhmm(s.at)} {s.name}</Text>
        ))}
        {snap && <Text dimColor>scan {hhmm(snap.scannedAt)}</Text>}
      </Box>
    )
  })
}
