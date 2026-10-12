from amem import confidence, signals
from amem.events import Event
from amem.store import Store


def test_confidence_from_evidence_counts():
    assert confidence.confidence(0, 0) == 0.5
    assert round(confidence.confidence(3, 1), 2) == 0.67
    assert round(confidence.confidence(5, 1), 2) == 0.75
    assert confidence.is_conflicted({"evidence": ["a"], "counter_evidence": ["b"]})
    assert not confidence.is_conflicted({"evidence": ["a", "b"], "counter_evidence": ["c"]})


def E(kind, name, target=None, ok=None):
    return Event("t", kind, name, target, ok)


def test_signals_detect_each_kind():
    events = [
        E("tool", "Bash", "pytest", False),
        E("tool", "Edit", "a.py", True),
        E("tool", "Bash", "pytest", True),
        E("correction", "아니"),
        E("turn", "aborted"),
    ]
    kinds = {s.kind for s in signals.detect(events)}
    assert {"retry_success", "correction", "interrupted"} <= kinds


def test_repeated_sequence_ignores_read_only_loops():
    reads = [E("tool", n, ok=True) for n in ["Read", "Grep", "Glob"] * 4]
    assert not [s for s in signals.detect(reads) if s.kind == "repeated_sequence"]
    work = [E("tool", n, ok=True) for n in ["Edit", "Bash", "Read"] * 3]
    assert [s for s in signals.detect(work) if s.kind == "repeated_sequence"]


def test_repeated_failure():
    fails = [E("tool", "Bash", "x", False) for _ in range(3)]
    assert [s for s in signals.detect(fails) if s.kind == "repeated_failure"]


def test_ids_include_machine_so_two_pcs_never_collide(tmp_path):
    mac, win = Store(tmp_path, "mac"), Store(tmp_path, "win-work")
    a = mac.add("opinion", {"statement": "x"}, "x")
    b = win.add("opinion", {"statement": "y"}, "y")
    c = mac.add("opinion", {"statement": "z"}, "z")
    assert "_mac_001" in a.id and "_win-work_001" in b.id and "_mac_002" in c.id
    assert mac.get(b.id).meta["statement"] == "y"


def test_state_files_are_per_machine(tmp_path):
    mac, win = Store(tmp_path, "mac"), Store(tmp_path, "win-work")
    mac.save_state("processed", {"a": 1})
    assert win.load_state("processed") == {}
    assert (tmp_path / ".amem" / "processed-mac.json").exists()
