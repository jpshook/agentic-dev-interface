from pathlib import Path

from adi.engine.repo_explorer import detect_repo_profile


def test_detect_node_typescript_profile(tmp_path: Path) -> None:
    root = tmp_path / "node-repo"
    root.mkdir()
    (root / "package.json").write_text(
        '{"name":"app","scripts":{"test":"vitest","build":"tsc","lint":"eslint .","typecheck":"tsc -p tsconfig.json"}}',
        encoding="utf-8",
    )
    (root / "tsconfig.json").write_text("{}", encoding="utf-8")
    (root / "pnpm-lock.yaml").write_text("lockfileVersion: 9", encoding="utf-8")

    profile = detect_repo_profile(root)

    assert profile.language == "typescript"
    assert profile.package_manager == "pnpm"
    assert profile.commands["test"] == "pnpm test"


def test_detect_python_profile(tmp_path: Path) -> None:
    root = tmp_path / "py-repo"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='py'\n", encoding="utf-8")

    profile = detect_repo_profile(root)

    assert profile.language == "python"
    assert profile.package_manager == "pip"
    assert profile.commands["test"] == "pytest -q"


def test_detect_go_profile(tmp_path: Path) -> None:
    root = tmp_path / "go-repo"
    root.mkdir()
    (root / "go.mod").write_text("module example.com/test\n", encoding="utf-8")

    profile = detect_repo_profile(root)

    assert profile.language == "go"
    assert profile.commands["test"] == "go test ./..."


def test_detect_rust_profile(tmp_path: Path) -> None:
    root = tmp_path / "rust-repo"
    root.mkdir()
    (root / "Cargo.toml").write_text("[package]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8")

    profile = detect_repo_profile(root)

    assert profile.language == "rust"
    assert profile.package_manager == "cargo"
