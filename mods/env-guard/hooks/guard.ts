// git add/commit 명령에서 .env 계열 파일 인자를 찾는다 (.env.example 등 템플릿은 허용)
const GIT_STAGE = /\bgit\s+(?:-C\s+\S+\s+)?(add|commit)\b/
const ENV_FILE = /(^|[\/\\])\.env(\.[\w.-]+)?$/
const TEMPLATE = /\.(example|sample|template|dist)$/

export function findEnvFiles(command: string): string[] {
  // && ; | 로 이어진 명령을 쪼개서 git add/commit 구간만 본다
  return command
    .split(/&&|\|\||;|\|/)
    .filter(part => GIT_STAGE.test(part))
    .flatMap(part => part.trim().split(/\s+/))
    .map(token => token.replace(/^['"]|['"]$/g, ''))
    .filter(token => ENV_FILE.test(token) && !TEMPLATE.test(token))
}
