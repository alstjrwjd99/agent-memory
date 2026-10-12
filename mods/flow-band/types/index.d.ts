export type StepStatus = 'done' | 'now' | 'next'
export type Step = { label: string; status: StepStatus }

// 프로젝트(폴더) 하나의 작업 흐름
export type Flow = {
  project: string
  goal: string
  steps: Step[]
  // Claude가 사용자 답을 기다리는 질문 (없으면 null)
  waiting: string | null
  at: number
}

declare module 'claude-code' {
  interface PluginState {
    'flow-band': { flow: Flow | null; hidden: boolean; toolsSince: number; turnsSince: number; updating: boolean }
  }
}
