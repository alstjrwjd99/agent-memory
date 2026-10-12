// 순수 함수 모음 (맥/윈도우 경로 공통 처리)
import type { MemoryEvent } from '../types'

// 윈도우 역슬래시를 / 로 통일하고 끝 슬래시 제거
export const norm = (p: string): string => p.replace(/\\/g, '/').replace(/\/+$/, '')

// cwd가 업무 경로에 속하면 work, 아니면 기본 scope (윈도우는 대소문자 무시)
export function scopeOf(cwd: string, workPaths: string, defaultScope: string): 'personal' | 'work' {
  const c = norm(cwd).toLowerCase()
  const hit = workPaths
    .split(',')
    .map(s => norm(s.trim()).toLowerCase())
    .filter(Boolean)
    .some(prefix => c === prefix || c.startsWith(prefix + '/'))
  if (hit) return 'work'
  return defaultScope === 'work' ? 'work' : 'personal'
}

// 사용자가 Claude 판단을 고친 신호 (암묵지 후보). 원문은 저장하지 않고 키워드만
const CORRECTION = /^\s*(아니(?:야|요|라)?|그게 아니|그거 말고|다시 ?해\S*|틀렸\S*|잘못\S*|no|wrong|that's not)(?=[\s,.!?]|$)/i
export function correctionOf(text: string): string | null {
  return CORRECTION.exec(text)?.[1]?.trim().toLowerCase() ?? null
}

// 도구 대상: 파일 경로는 cwd 기준 상대경로, Bash는 첫 단어(명령 이름)만
export function targetOf(tool: string, input: Record<string, unknown>, cwd: string): string | undefined {
  const path = input.file_path ?? input.notebook_path ?? input.path
  if (typeof path === 'string') {
    const p = norm(path)
    const base = norm(cwd)
    return p.toLowerCase().startsWith(base.toLowerCase() + '/') ? p.slice(base.length + 1) : p.split('/').pop()
  }
  if (tool === 'Bash' && typeof input.command === 'string') {
    // 앞쪽 환경변수 대입(TOKEN=xxx)은 건너뛰고, 명령 이름은 basename만, 안전한 글자만 허용
    const words = input.command.trim().split(/\s+/).filter(w => !/^\w+=/.test(w))
    const head = safeWord(words[0]?.split(/[\/\\]/).pop())
    if (!head) return undefined
    const sub = SUBCOMMAND_TOOLS.has(head) ? safeWord(words[1]) : undefined
    return sub ? `${head} ${sub}` : head
  }
  return undefined
}

// git commit 처럼 하위명령까지 의미 있는 도구
const SUBCOMMAND_TOOLS = new Set(['git', 'npm', 'uv', 'pnpm', 'docker', 'claude', 'gh'])

// 명령 이름으로 보이는 짧은 토큰만 통과 (비밀값/경로/옵션 차단)
function safeWord(w: string | undefined): string | undefined {
  return w && /^[A-Za-z0-9._-]{1,32}$/.test(w) && !w.startsWith('-') ? w : undefined
}

// store/events/<machine>/<YYYY-MM-DD>_<세션앞8자>.jsonl
export function eventFile(store: string, machine: string, startedAt: string, sessionId: string): string {
  return `${norm(store)}/events/${machine}/${startedAt.slice(0, 10)}_${sessionId.slice(0, 8)}.jsonl`
}

export const toJsonl = (events: readonly MemoryEvent[]): string => events.map(e => JSON.stringify(e)).join('\n') + '\n'

// 로컬 시간대 오프셋을 붙인 ISO 문자열 (두 PC 모두 KST지만 명시)
export function isoLocal(d: Date): string {
  const off = -d.getTimezoneOffset()
  const sign = off >= 0 ? '+' : '-'
  const pad = (n: number) => String(Math.floor(Math.abs(n))).padStart(2, '0')
  const local = new Date(d.getTime() + off * 60000).toISOString().slice(0, 19)
  return `${local}${sign}${pad(off / 60)}:${pad(off % 60)}`
}
