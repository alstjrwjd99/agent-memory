export type Visibility = 'public' | 'private' | 'unknown'

declare module 'claude-code' {
  interface PluginState {
    // 원격 URL → 공개 여부 캐시 (세션 동안)
    'public-guard': { visibility: Record<string, Visibility> }
  }
}
