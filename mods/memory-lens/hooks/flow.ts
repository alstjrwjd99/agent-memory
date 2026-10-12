// 흐름 요약 파싱/표시 유틸 (순수 함수, 테스트 대상)
import type { Flow, OtherFlow, Step } from '../types'

export const STATUSES = new Set(['done', 'now', 'next'])

// 모델 응답에서 첫 JSON 객체를 꺼내 검증. 이상하면 null
export function parseFlow(text: string, project: string, now: number): Flow | null {
  const m = /\{[\s\S]*\}/.exec(text)
  if (!m) return null
  try {
    const d = JSON.parse(m[0]) as { goal?: unknown; steps?: unknown; waiting?: unknown; detail?: unknown }
    const steps = (Array.isArray(d.steps) ? d.steps : [])
      .filter((s): s is Step => !!s && typeof s.label === 'string' && STATUSES.has(s.status))
      .map(s => ({ label: s.label.trim().slice(0, 40), status: s.status }))
      .slice(0, 12)
    if (steps.length === 0) return null
    const waiting = typeof d.waiting === 'string' && d.waiting.trim() && d.waiting.trim() !== 'null' ? d.waiting.trim().slice(0, 120) : null
    const detail = typeof d.detail === 'string' && d.detail.trim() && d.detail.trim() !== 'null' ? d.detail.trim().slice(0, 60) : null
    return { project, goal: typeof d.goal === 'string' ? d.goal.trim().slice(0, 60) : '', steps, detail, waiting, at: now }
  } catch {
    return null
  }
}

const MARK: Record<Step['status'], string> = { done: '✓', now: '●', next: '○' }

// 폭에 맞게 흐름 한 줄: 지금 단계 중심으로 앞뒤를 줄이고 잘린 쪽엔 …
export function stepsLine(steps: readonly Step[], width: number): string {
  const cells = steps.map(s => `${MARK[s.status]} ${s.label}`)
  const join = (xs: string[]) => xs.join(' → ')
  if (join(cells).length <= width) return join(cells)
  let now = steps.findIndex(s => s.status === 'now')
  if (now < 0) now = steps.findIndex(s => s.status === 'next')
  if (now < 0) now = steps.length - 1
  let lo = now
  let hi = now
  // 지금 단계부터 뒤(남은 단계) 하나, 앞(끝난 단계) 하나씩 번갈아 넓힌다
  for (let grew = true; grew; ) {
    grew = false
    for (const side of ['hi', 'lo'] as const) {
      const nlo = side === 'lo' ? lo - 1 : lo
      const nhi = side === 'hi' ? hi + 1 : hi
      if (nlo < 0 || nhi >= cells.length) continue
      const text = (nlo > 0 ? '… ' : '') + join(cells.slice(nlo, nhi + 1)) + (nhi < cells.length - 1 ? ' …' : '')
      if (text.length <= width) {
        lo = nlo
        hi = nhi
        grew = true
      }
    }
  }
  const text = (lo > 0 ? '… ' : '') + join(cells.slice(lo, hi + 1)) + (hi < cells.length - 1 ? ' …' : '')
  return text.length <= width ? text : `${cells[now]}`.slice(0, width)
}

// 요약할 대화: 최근 메시지 텍스트 + 쓴 도구 이름 (길이 제한)
export function transcriptDigest(messages: readonly { role: string; text: string; toolUses?: readonly { tool?: string }[] }[], max = 40, per = 400): string {
  return messages
    .slice(-max)
    .map(m => {
      const tools = (m.toolUses ?? []).map(t => t.tool).filter(Boolean)
      const text = m.text.replace(/\s+/g, ' ').trim().slice(0, per)
      return `[${m.role === 'user' ? 'U' : 'A'}] ${text}${tools.length ? ` (도구: ${tools.join(',')})` : ''}`
    })
    .filter(l => l.length > 5)
    .join('\n')
}

export function buildPrompt(digest: string, prev: Flow | null): string {
  return `아래는 사용자와 AI 코딩 에이전트의 최근 대화다. 사용자가 다른 일을 하다 돌아왔을 때 한눈에 보도록 "작업 흐름"을 요약하라.

규칙 (2단 흐름):
- goal: 이 프로젝트의 큰 목표 한 구절 (20자 이내). 중간에 끼어든 작은 작업(버그 수정, 화면 조정, 질문 답변)으로 바꾸지 마라
- steps: 큰 목표의 굵직한 단계 3~8개. status는 done(끝남) / now(지금, 1개) / next(남음). label은 12자 이내 명사구
- detail: 지금 실제로 손대고 있는 작은 작업 (25자 이내). 큰 단계에 들어가지 않는 세부 작업은 여기에만 쓴다
- 이전 흐름이 있으면 goal과 steps 이름을 그대로 유지하고 상태만 갱신하라. 사용자가 명시적으로 다른 큰 일로 넘어갔을 때만 새로 짜라
- waiting: 에이전트의 마지막 답변이 사용자에게 결정/확인을 묻고 끝났으면 그 질문을 25자 이내로, 아니면 null
- JSON만 출력: {"goal": "...", "steps": [{"label": "...", "status": "done"}], "detail": "..." 또는 null, "waiting": "..." 또는 null}

## 이전 흐름
${prev ? JSON.stringify({ goal: prev.goal, steps: prev.steps, detail: prev.detail, waiting: prev.waiting }) : '(없음)'}

## 최근 대화
${digest}`
}

// 폴더 경로 → 프로젝트 이름 (마지막 폴더)
export const projectOf = (cwd: string): string => cwd.replace(/\\/g, '/').replace(/\/+$/, '').split('/').pop() || cwd

export const storeKey = (cwd: string): string => `flow:${cwd.replace(/\\/g, '/').toLowerCase()}`

// 세로 흐름: 끝난 단계가 많으면 앞쪽을 "✓ N개 완료"로 접는다
export type FlowRow = { kind: 'folded'; count: number } | ({ kind: 'step' } & Step)

export function verticalSteps(steps: readonly Step[], keepDone = 3): FlowRow[] {
  const doneIdx = steps.map((s, i) => (s.status === 'done' ? i : -1)).filter(i => i >= 0)
  const fold = Math.max(0, doneIdx.length - keepDone)
  const out: FlowRow[] = []
  if (fold > 0) out.push({ kind: 'folded', count: fold })
  steps.forEach((s, i) => {
    if (s.status === 'done' && doneIdx.indexOf(i) < fold) return
    out.push({ kind: 'step', ...s })
  })
  return out
}

// 다른 폴더들의 흐름 → 최근 순 한 줄 요약 (지금 폴더 제외)
export function otherFlows(flows: readonly Flow[], currentProject: string, limit = 4): OtherFlow[] {
  return flows
    .filter(f => f && f.project && f.project !== currentProject && Array.isArray(f.steps))
    .sort((a, b) => b.at - a.at)
    .slice(0, limit)
    .map(f => ({ project: f.project, now: f.steps.find(s => s.status === 'now')?.label ?? null, waiting: f.waiting ?? null, at: f.at }))
}

// 경과 시간: 방금 / 12분 / 3시간 / 2일
export function ago(at: number, now: number): string {
  const m = Math.max(0, Math.round((now - at) / 60_000))
  if (m < 1) return '방금'
  if (m < 60) return `${m}분`
  if (m < 60 * 24) return `${Math.round(m / 60)}시간`
  return `${Math.round(m / 1440)}일`
}
