from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_quickstart_does_not_bind_port_80():
    text = (ROOT / "compose.yaml").read_text()
    assert "127.0.0.1" in text
    assert "80:80" not in text
    assert "18080" in text
    assert "local-demo-key" not in text
    assert "TWIN_DASHBOARD_OPEN:-0" in text or "TWIN_DASHBOARD_OPEN:-0}" in text
    assert "TWIN_ENV:-prod" in text


def test_s3_endpoint_is_portable_and_alfalfa_has_no_host_ports():
    overlay = (ROOT / "alfalfa.local.yaml").read_text()
    alfalfa = (ROOT / "compose.alfalfa.yaml").read_text()
    assert "kubernetes.docker.internal" not in overlay
    assert "kubernetes.docker.internal" not in alfalfa
    assert "minio:9000" in overlay
    assert "127.0.0.1:80" not in overlay
    assert "published: 80" not in overlay
    assert "!reset []" in overlay


def test_legacy_direct_energyplus_prototype_is_gone():
    for name in (
        "app/standalone_server.py",
        "Dockerfile.standalone",
        "compose.standalone.yaml",
        "pacer_experiment.py",
        "CHECKPOINT.md",
    ):
        assert not (ROOT / name).exists(), name
