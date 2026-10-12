"""LLM 백엔드. 기본은 claude -p (두 PC의 Claude Code 로그인 재사용, API 키 불필요)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Protocol


class LLMError(RuntimeError):
    pass


class Backend(Protocol):
    def json(self, prompt: str, schema: dict) -> dict: ...


class ClaudeCLI:
    def __init__(self, model: str, timeout: int = 600):
        self.model = model
        self.timeout = timeout

    def json(self, prompt: str, schema: dict) -> dict:
        # 윈도우: claude.cmd(npm shim)는 cmd.exe를 거쳐 JSON 인자의 따옴표가 깨질 수 있어 claude.exe 우선
        exe = shutil.which("claude.exe") if os.name == "nt" else None
        exe = exe or shutil.which("claude")
        if not exe:
            raise LLMError("claude CLI를 찾을 수 없음 (PATH 확인)")
        cmd = [
            exe, "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(schema, ensure_ascii=True, separators=(",", ":")),
            "--model", self.model,
            "--tools", "",
            "--no-session-persistence",
        ]
        # AMEM_INTERNAL: memory-events mod가 엔진 자신의 호출을 기록하지 않도록
        env = {**os.environ, "AMEM_INTERNAL": "1"}
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                env=env, cwd=tempfile.gettempdir(), timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"claude -p 시간 초과 ({self.timeout}s)") from e
        if proc.returncode != 0:
            raise LLMError(f"claude -p 실패 (exit {proc.returncode}): {proc.stderr.strip()[:500]}")
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise LLMError(f"claude -p 출력 파싱 실패: {proc.stdout[:300]}") from e
        if out.get("is_error"):
            raise LLMError(f"claude -p 오류: {out.get('result') or out.get('subtype')}")
        data = out.get("structured_output")
        if not isinstance(data, dict):
            raise LLMError("structured_output 없음 (스키마 검증 실패 가능)")
        return data


class AnthropicSDK:
    """API 키(또는 ant auth login)가 있는 환경용. 서버측 refusal fallback 기본 활성화."""

    def __init__(self, model: str):
        import anthropic

        self.anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model

    def json(self, prompt: str, schema: dict) -> dict:
        a = self.anthropic
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"format": {"type": "json_schema", "schema": schema}, "effort": "medium"},
                messages=[{"role": "user", "content": prompt}],
            )
        except a.RateLimitError as e:
            raise LLMError("rate limit, 잠시 후 재시도") from e
        except a.APIStatusError as e:
            raise LLMError(f"API 오류 {e.status_code}: {e.message}") from e
        except a.APIConnectionError as e:
            raise LLMError("네트워크 오류") from e
        if resp.stop_reason == "refusal":
            raise LLMError("모델이 요청을 거절함")
        if resp.stop_reason == "max_tokens":
            raise LLMError("출력이 max_tokens에서 잘림")
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"JSON 파싱 실패: {text[:300]}") from e


def make(backend: str, model: str) -> Backend:
    if backend == "sdk":
        return AnthropicSDK(model)
    if backend == "claude-cli":
        return ClaudeCLI(model)
    raise LLMError(f"알 수 없는 backend: {backend}")
