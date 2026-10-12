import type { Register } from 'claude-code'
import { findEnvFiles } from './guard.ts'

export const register: Register = on => {
  on('tool.call', { tool: 'Bash' }, ($, e, next) => {
    const hits = findEnvFiles(e.command)
    if (hits.length === 0) return next(e)

    $.ui.toast(`env-guard: ${hits.join(', ')} 커밋 차단`)
    return { deny: `${$.plugin.name}: .env 파일은 커밋 금지 (${hits.join(', ')}). .gitignore에 추가하고 해당 파일은 빼고 진행할 것.` }
  }).catch(($, e, next) =>
    // 가드 자체가 실패하면 안전하게 막는다
    next.called ? next(e) : { deny: `${$.plugin.name}: 가드 실행 실패` },
  )
}
