import subprocess
from pathlib import Path

from adi.cli.main import main
from adi.engine.yaml_utils import load_yaml


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init"], check=True, capture_output=True)
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "init",
        ],
        check=True,
        capture_output=True,
    )


def test_repo_cli_init_explore_info_doctor(tmp_path: Path, monkeypatch, capsys) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    repo_path = tmp_path / "DemoRepo"
    _init_git_repo(repo_path)
    (repo_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    assert main(["repo", "init", "--path", str(repo_path)]) == 0
    init_out = capsys.readouterr().out
    init_payload = load_yaml(init_out)
    repo_id = init_payload["repo"]["id"]

    assert main(["repo", "explore", "--repo", repo_id]) == 0
    explore_out = capsys.readouterr().out
    explore_payload = load_yaml(explore_out)
    assert explore_payload["profile"]["language"] == "python"

    assert main(["repo", "info", "--repo", repo_id]) == 0
    info_out = capsys.readouterr().out
    info_payload = load_yaml(info_out)
    assert info_payload["artifact"]["frontmatter"]["id"] == repo_id

    assert main(["repo", "doctor", "--repo", repo_id]) == 0
    doctor_out = capsys.readouterr().out
    doctor_payload = load_yaml(doctor_out)
    assert doctor_payload["healthy"] is True


def test_repo_delete_removes_registered_artifacts_recursively(tmp_path: Path, monkeypatch, capsys) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    repo_path = tmp_path / "DeleteRepo"
    _init_git_repo(repo_path)
    (repo_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    assert main(["repo", "init", "--path", str(repo_path)]) == 0
    repo_id = load_yaml(capsys.readouterr().out)["repo"]["id"]

    assert main(["repo", "explore", "--repo", repo_id]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "spec",
                "create",
                "--repo",
                repo_id,
                "--title",
                "Delete repo spec",
                "--id",
                "SP-REPO-DEL",
                "--execution-mode",
                "manual",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["spec", "analyze", "SP-REPO-DEL"]) == 0
    capsys.readouterr()
    assert main(["spec", "decompose", "SP-REPO-DEL"]) == 0
    capsys.readouterr()

    repo_state_dir = adi_home / "repos" / repo_id
    assert repo_state_dir.exists()

    assert main(["repo", "delete", "--repo", repo_id]) == 0
    delete_payload = load_yaml(capsys.readouterr().out)
    assert delete_payload["deleted"] is True
    assert not repo_state_dir.exists()

    assert main(["repos", "list"]) == 0
    repos_payload = load_yaml(capsys.readouterr().out)
    assert repos_payload["summary"]["total"] == 0
    assert main(["repo", "info", "--repo", repo_id]) == 1
