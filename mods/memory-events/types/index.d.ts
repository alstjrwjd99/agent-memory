// events.jsonl 한 줄: 내용 원문 없이 "무슨 일이 있었는지" 포인터만 남긴다
export type MemoryEvent = {
  ts: string
  kind: 'tool' | 'correction' | 'turn'
  // tool: 도구 이름 / correction: 매칭된 교정 키워드 / turn: 종료 사유
  name: string
  // 도구 대상 (cwd 기준 상대경로 또는 파일명), 없으면 생략
  target?: string
  ok?: boolean
}

// prior: 이 프로세스가 시작되기 전 같은 세션 파일에 있던 내용 (재시작/--resume 시 보존)
export type EventBuffer = { sessionId: string; startedAt: string; events: MemoryEvent[]; prior?: string; priorLoaded?: boolean }

declare module 'claude-code' {
  interface PluginState {
    'memory-events': { buffer: EventBuffer | null }
  }
}
