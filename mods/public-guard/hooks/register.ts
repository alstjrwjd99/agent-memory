import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { Visibility } from '../types'
import { expandHome, findTerms, isPublishing, locate, parseTerms, parseVisibility, repoDirOf } from './scan.ts'

const visibility = atom({ plugin: 'public-guard', key: 'visibility' } as const, {} as Record<string, Visibility>)

async function git($: EngineInterface, dir: string, args: string[]): Promise<string> {
  const r = await $.process.run(['git', '-C', dir, ...args], { timeoutMs: 15_000 })
  return r.exitCode === 0 ? r.stdout : ''
}

// 원격이 공개 GitHub 저장소인가 (gh로 확인, 세션 동안 캐시)
async function isPublic($: EngineInterface, dir: string): Promise<boolean> {
  const remote = (await git($, dir, ['remote', 'get-url', 'origin'])).trim()
  if (!remote.includes('github.com')) return false
  const cache = await read($, visibility)
  let v = cache[remote]
  if (!v) {
    const r = await $.process.run(['gh', 'repo', 'view', remote, '--json', 'isPrivate,visibility'], { timeoutMs: 15_000 })
    v = r.exitCode === 0 ? parseVisibility(r.stdout) : 'unknown'
    await update($, visibility, c => ({ ...c, [remote]: v as Visibility }))
  }
  // 확인 못 하면 공개로 간주 (막는 쪽이 안전)
  return v !== 'private'
}

async function terms($: EngineInterface, options: PluginOptions, home: string): Promise<string[]> {
  const file = expandHome(String(options.termsFile || '~/.config/agent-memory/sensitive-terms.txt'), home)
  return (await $.fs.exists(file)) ? parseTerms(String(await $.fs.read(file))) : []
}

// 이번에 나갈 내용: 명령 문자열(커밋 메시지) + 업스트림 대비 변경 + 아직 안 올린 커밋 메시지 + 새 파일
async function outgoing($: EngineInterface, dir: string, command: string): Promise<string> {
  const upstream = (await git($, dir, ['rev-parse', '--abbrev-ref', '@{u}'])).trim()
  const diff = upstream
    ? await git($, dir, ['diff', upstream])
    : (await git($, dir, ['diff', '--cached'])) + (await git($, dir, ['diff']))
  const logs = upstream ? await git($, dir, ['log', `${upstream}..HEAD`, '--format=%B']) : ''
  const untracked = (await git($, dir, ['ls-files', '--others', '--exclude-standard'])).split('\n').filter(Boolean).slice(0, 200)
  let added = ''
  for (const f of untracked) {
    const path = `${dir}/${f}`
    try {
      added += `\n+++ b/${f}\n` + String(await $.fs.read(path)).split('\n').map(l => `+${l}`).join('\n')
    } catch {}
  }
  return [command, logs, diff, added].join('\n')
}

export const register: Register = (on, options) => {
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    if (!isPublishing(e.command)) return next(e)
    const home = (await $.env.get('HOME')) ?? (await $.env.get('USERPROFILE')) ?? ''
    const list = await terms($, options, home)
    if (list.length === 0) return next(e)
    const raw = repoDirOf(e.command)
    const dir = raw ? expandHome(raw, home) : await $.session.cwd()
    if (!(await isPublic($, dir))) return next(e)
    const text = await outgoing($, dir, e.command)
    const hits = findTerms(text, list)
    if (hits.length === 0) return next(e)
    const where = hits.map(t => `${t}${locate(text, t).length ? ` (${locate(text, t).slice(0, 3).join(', ')})` : ''}`).join('; ')
    $.ui.toast(`public-guard: 공개 저장소로 민감어가 나가려 해서 막았어요: ${hits.join(', ')}`)
    return {
      deny: `${$.plugin.name}: 공개 저장소(${dir})에 민감 식별자가 포함됨: ${where}. 가상 이름(acme, billing 등)으로 바꾼 뒤 다시 시도할 것. 커밋 메시지도 확인.`,
    }
  }).catch(($, e, next) =>
    // 검사 자체가 실패하면 막지 않고 통과 (작업 흐름을 멈추지 않게). 실패 사실은 알림
    next.called ? next(e) : ($.ui.toast('public-guard: 검사 실패, 통과시킴'), next(e)),
  )
}
