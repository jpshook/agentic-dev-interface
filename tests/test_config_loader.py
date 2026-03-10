from pathlib import Path

from adi.engine.config_loader import ConfigLoader
from adi.engine.yaml_utils import dump_yaml


def test_config_loader_merges_defaults_global_and_repo_override(tmp_path: Path) -> None:
    loader = ConfigLoader(adi_home=tmp_path / ".adi")
    loader.ensure_initialized()

    global_adi = loader.config_dir / "adi.yaml"
    global_adi.write_text(
        dump_yaml(
            {
                "execution": {
                    "default_timeout_seconds": 30,
                },
                "verification": {
                    "default_checks": ["test"],
                },
            }
        ),
        encoding="utf-8",
    )

    repo_override = loader.repos_dir / "repo-1" / "state" / "repo-config.yaml"
    repo_override.parent.mkdir(parents=True, exist_ok=True)
    repo_override.write_text(
        dump_yaml({"execution": {"default_timeout_seconds": 10}}),
        encoding="utf-8",
    )

    effective = loader.load_effective_config(repo_id="repo-1")
    assert effective["adi"]["execution"]["default_timeout_seconds"] == 10
    assert effective["adi"]["verification"]["default_checks"] == ["test"]


def test_repos_registry_round_trip(tmp_path: Path) -> None:
    loader = ConfigLoader(adi_home=tmp_path / ".adi")
    payload = [{"id": "repo-1", "name": "repo-1", "root": "/tmp/repo"}]
    loader.save_repos_registry(payload)

    loaded = loader.load_repos_registry()
    assert loaded == payload
