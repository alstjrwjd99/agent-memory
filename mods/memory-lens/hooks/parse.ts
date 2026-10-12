// 기억 파일/경로 해석 유틸 (순수 함수, 테스트 대상)

// frontmatter의 type 추출: `type:` → `metadata.type` → tags memory/x → 파일명 접두어 순
export function memoryType(fileName: string, text: string): string {
  const fm = /^---\n([\s\S]*?)\n---/.exec(text)?.[1] ?? ''
  const direct = /^\s*type:\s*([\w-]+)/m.exec(fm)?.[1]
  if (direct) return direct
  const tag = /memory\/([\w-]+)/.exec(fm)?.[1]
  if (tag) return tag
  return /^([a-z]+)_/.exec(fileName)?.[1] ?? 'other'
}

// 윈도우 역슬래시를 / 로 통일
const norm = (p: string): string => p.replace(/\\/g, '/')

// 경로가 기억/스킬 저장인지 판정
export function classifyPath(raw: string): { kind: 'memory' | 'skill'; name: string } | null {
  const path = norm(raw)
  if (!path.endsWith('.md')) return null
  const memory = /\/\.claude\/projects\/[^/]+\/memory\/([^/]+)\.md$/.exec(path)
  if (memory?.[1]) return memory[1] === 'MEMORY' ? null : { kind: 'memory', name: memory[1] }
  const skill = /\/\.claude\/skills\/([^/]+)\/SKILL\.md$/.exec(path)
  if (skill?.[1]) return { kind: 'skill', name: skill[1] }
  return null
}

// 플러그인 경로에서 ~/.claude 와 홈 프로젝트 메모리 경로 유도
// Claude Code 프로젝트 폴더명 규칙: 영숫자 외 문자를 - 로 (C:\Users\a → C--Users-a)
// 홈 디렉토리(HOME 또는 USERPROFILE) 기준으로 경로 유도
export function paths(homeRaw: string): { claudeDir: string; memoryDir: string; skillsDir: string } {
  const home = norm(homeRaw).replace(/\/+$/, '')
  const claudeDir = `${home}/.claude`
  return {
    claudeDir,
    memoryDir: `${claudeDir}/projects/${home.replace(/[^A-Za-z0-9]/g, '-')}/memory`,
    skillsDir: `${claudeDir}/skills`,
  }
}
