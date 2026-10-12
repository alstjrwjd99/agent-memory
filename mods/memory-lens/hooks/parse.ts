// 경로/제안 해석 유틸 (순수 함수, 테스트 대상)

// 윈도우 역슬래시를 / 로 통일
export const norm = (p: string): string => p.replace(/\\/g, '/').replace(/\/+$/, '')

// Claude가 Claude Code 메모리나 스킬 파일을 쓰는지 판정 (저장 알림용)
export function classifyPath(raw: string): { kind: 'memory' | 'skill'; name: string } | null {
  const path = norm(raw)
  if (!path.endsWith('.md')) return null
  const memory = /\/\.claude\/projects\/[^/]+\/memory\/([^/]+)\.md$/.exec(path)
  if (memory?.[1]) return memory[1] === 'MEMORY' ? null : { kind: 'memory', name: memory[1] }
  const skill = /\/\.claude\/skills\/([^/]+)\/SKILL\.md$/.exec(path)
  if (skill?.[1]) return { kind: 'skill', name: skill[1] }
  return null
}

// 설정이 비어 있으면 홈 기준 기본 경로
export function resolvePaths(home: string, store: string, engineDir: string): { store: string; engineDir: string } {
  const h = norm(home)
  return {
    store: store ? norm(store) : `${h}/workspace/memory-personal`,
    engineDir: engineDir ? norm(engineDir) : `${h}/workspace/agent-memory/engine`,
  }
}

type ProposalItem = { n: number; op: string; status: string; [k: string]: unknown }

const str = (v: unknown): string => (typeof v === 'string' ? v : '')
const len = (v: unknown): number => (Array.isArray(v) ? v.length : 0)

// 근거 개수로 계산하는 confidence (엔진과 같은 공식)
export const confidence = (support: number, counter: number): number => (support + 1) / (support + counter + 2)

// 제안 항목 한 줄 요약 (engine review.describe 와 같은 의미)
export function describe(it: ProposalItem): string {
  switch (it.op) {
    case 'new_opinion':
      return `[판단 ${confidence(len(it.supports), len(it.contradicts)).toFixed(2)}] ${str(it.statement)}`
    case 'new_procedure':
      return `[절차] ${str(it.trigger)}`
    case 'observe':
      return `[관찰] ${str(it.subject)}: ${str(it.summary)}`
    case 'evidence':
      return `[근거] ${str(it.id)} +${len(it.supports)} / 반례 +${len(it.contradicts)}`
    case 'invalidate':
      return `[무효화] ${str(it.id)}: ${str(it.reason)}`
    default:
      return `[${it.op}]`
  }
}

// proposals/*.json 텍스트들 → 승인 대기 항목
export function pendingItems(files: readonly string[]): { pid: string; n: number; text: string }[] {
  const out: { pid: string; n: number; text: string }[] = []
  for (const text of files) {
    try {
      const p = JSON.parse(text) as { id: string; status: string; items: ProposalItem[] }
      if (p.status !== 'pending') continue
      for (const it of p.items) if (it.status === 'pending') out.push({ pid: p.id, n: it.n, text: describe(it) })
    } catch {
      // 동기화 중 깨진 파일은 건너뜀
    }
  }
  return out
}

// recall을 건너뛸 프롬프트: 슬래시 명령, 너무 짧은 대답(ㄱㄱ, 응 등)
export function shouldRecall(text: string): boolean {
  const t = text.trim()
  return t.length >= 6 && !t.startsWith('/')
}

export const clip = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

// 판단 변화 한 줄: ↑ / ↓ / NEW
export function changeLine(c: { label: string; from: number | null; to: number }, width: number): string {
  const label = clip(c.label, width)
  if (c.from === null) return `NEW ${label} ${c.to.toFixed(2)}`
  const arrow = c.to > c.from ? '↑' : c.to < c.from ? '↓' : '='
  return `${arrow} ${label} ${c.from.toFixed(2)}→${c.to.toFixed(2)}`
}
