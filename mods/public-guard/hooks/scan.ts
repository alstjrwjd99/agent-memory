// 순수 함수: 명령 해석, 민감어 매칭 (테스트 대상)

// git commit / push 가 들어 있는 명령인가 (&&, ; 로 이어진 것 포함)
// 따옴표 안 문자열(커밋 메시지, echo 인자)은 빼고 본다
export const isPublishing = (command: string): boolean =>
  /\bgit\b[^;&|]*\b(commit|push)\b/.test(command.replace(/"[^"]*"|'[^']*'/g, '""'))

// 명령이 어느 저장소에서 실행되는지: git -C <dir> 또는 앞쪽 cd <dir>, 없으면 null (= 세션 cwd)
export function repoDirOf(command: string): string | null {
  const c = /\bgit\s+-C\s+("([^"]+)"|'([^']+)'|(\S+))/.exec(command)
  if (c) return c[2] ?? c[3] ?? c[4] ?? null
  const cd = /(?:^|&&|;)\s*cd\s+("([^"]+)"|'([^']+)'|(\S+))/.exec(command)
  if (cd) return cd[2] ?? cd[3] ?? cd[4] ?? null
  return null
}

// 홈(~) 펼치기
export const expandHome = (p: string, home: string): string => (p === '~' || p.startsWith('~/') ? home + p.slice(1) : p)

// 민감어 목록 파일: 한 줄에 하나, # 주석, 빈 줄 무시
export const parseTerms = (text: string): string[] =>
  text.split(/\r?\n/).map(l => l.replace(/#.*/, '').trim()).filter(Boolean)

// 영문/숫자 용어는 단어 경계로(긴 단어 속 오탐 방지), 한글 등은 포함 여부로
export function findTerms(text: string, terms: readonly string[]): string[] {
  const hits = new Set<string>()
  for (const term of terms) {
    const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const re = /^[\w-]+$/.test(term) ? new RegExp(`(?<![A-Za-z0-9])${escaped}(?![A-Za-z0-9])`, 'i') : new RegExp(escaped, 'i')
    if (re.test(text)) hits.add(term)
  }
  return [...hits]
}

// gh repo view --json isPrivate,visibility 결과 해석
export function parseVisibility(stdout: string): 'public' | 'private' | 'unknown' {
  try {
    const d = JSON.parse(stdout) as { isPrivate?: boolean; visibility?: string }
    if (d.isPrivate === true || d.visibility === 'PRIVATE' || d.visibility === 'INTERNAL') return 'private'
    if (d.isPrivate === false || d.visibility === 'PUBLIC') return 'public'
  } catch {}
  return 'unknown'
}

// 매칭된 줄 위치 요약 (어느 파일에서 걸렸는지 보여주기용, diff 헤더 기준)
export function locate(diff: string, term: string): string[] {
  const files: string[] = []
  let file = ''
  const t = term.toLowerCase()
  for (const line of diff.split('\n')) {
    const m = /^\+\+\+ b\/(.+)$/.exec(line)
    if (m?.[1]) file = m[1]
    else if (line.startsWith('+') && line.toLowerCase().includes(t) && file && !files.includes(file)) files.push(file)
  }
  return files
}
