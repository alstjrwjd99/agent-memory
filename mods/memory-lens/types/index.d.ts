// 기억 현황 스냅샷
export type MemorySnapshot = {
  // frontmatter type별 개수 (feedback/project/reference/user/기타)
  byType: Record<string, number>
  skills: number
  scannedAt: number
}

// 이번 세션에 저장된 기억 한 건
export type SavedMemory = { at: number; kind: string; name: string }

declare module 'claude-code' {
  interface PluginState {
    'memory-lens': { snapshot: MemorySnapshot | null; saved: SavedMemory[]; turns: number }
  }
}
