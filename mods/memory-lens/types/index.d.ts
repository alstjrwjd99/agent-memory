// amem health JSON (engine/src/amem/health.py 와 같은 모양)
export type Health = {
  machine: string
  counts: Record<'world' | 'experience' | 'observation' | 'opinion' | 'procedure', number>
  new_today: number
  updated_today: number
  conflicts: string[]
  pending_sessions: number
  fresh_episodes: number
  pending_proposals: number
  recent_changes: { id: string; label: string; from: number | null; to: number; at: string }[]
}

export type Scope = 'personal' | 'work'

// store별 health (없는 store는 목록에 안 들어감)
export type StoreHealth = { scope: Scope; health: Health | null }

// 승인 대기 제안 한 항목 (화면용으로 요약)
export type PendingItem = { scope: Scope; pid: string; n: number; text: string }

// amem recall --json 의 hit (Memory Inspector용)
export type RecallHit = { id: string; kind: string; score: number; why: string[]; label: string }
export type LastRecall = { at: number; query: string; scope: string; hits: RecallHit[] }

declare module 'claude-code' {
  interface PluginState {
    'memory-lens': {
      stores: StoreHealth[]
      pending: PendingItem[]
      busy: string | null
      message: string | null
      saved: { at: number; name: string }[]
      turns: number
      recall: LastRecall | null
      loadedAt: number
    }
  }
}
