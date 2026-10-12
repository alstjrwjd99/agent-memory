import json

from amem import cli, config, transcript


def test_transcript_excerpt_skips_tags_and_tool_results(tmp_path):
    p = tmp_path / "t.jsonl"
    rows = [
        {"type": "user", "message": {"content": "<command-name>/x</command-name>"}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "big"}]}},
        {"type": "user", "message": {"content": "진짜 질문"}},
        {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "답"}]}},
        "broken line",
    ]
    p.write_text("\n".join(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    assert transcript.excerpt(p) == "[U] 진짜 질문\n[A] 답"


def test_cli_init_and_health_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AMEM_CONFIG", str(tmp_path / "cfg" / "config.yaml"))
    assert cli.main(["init", "--machine", "win-work", "--work", str(tmp_path / "w"), "--personal", str(tmp_path / "p")]) == 0
    cfg = config.load()
    assert cfg.machine == "win-work" and set(cfg.stores) == {"personal", "work"}
    assert (tmp_path / "w" / "episodes").is_dir() and (tmp_path / "w" / ".gitignore").exists()
    assert cli.main(["--store", "work", "health"]) == 0
    out = capsys.readouterr().out
    assert "Memory Health" in out and (tmp_path / "w" / ".amem" / "health-win-work.json").exists()
