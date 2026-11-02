import json

from scripts.experiments import run_dropout_campaign as runner


def test_dropout_binding_detects_replaced_checkpoint_and_scenario(monkeypatch, tmp_path):
    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    (raw / "manifest.json").write_text('{"revision":"pinned"}')
    campaign = tmp_path / "campaign"
    (campaign / "models").mkdir(parents=True)
    (campaign / "config.json").write_text('{}')
    (campaign / "summary.json").write_text('{}')
    checkpoint = campaign / "models/validate_doe_recommended_101.pt"
    checkpoint.write_bytes(b"first trained model")
    scenario = tmp_path / "scenario.npz"
    scenario.write_bytes(b"historical geometry")
    scenario.with_suffix('.json').write_text('{}')
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "prepare", lambda *args, **kwargs: scenario)
    monkeypatch.setattr(runner, "runtime_provenance", lambda: {"source_sha256": "code"})

    def bound():
        return runner.input_provenance({}, campaign, ["date"], ["leo"], [101])

    first = bound()
    assert bound() == first
    checkpoint.write_bytes(b"replacement model at same filename")
    replaced = bound()
    assert replaced["checkpoints_sha256"] != first["checkpoints_sha256"]
    scenario.write_bytes(b"different historical geometry")
    assert bound()["scenarios"] != replaced["scenarios"]
    json.dumps(first, allow_nan=False)
