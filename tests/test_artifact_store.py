from pathlib import Path

from adi.engine.artifact_store import ArtifactDocument, ArtifactStore


def test_artifact_store_write_read_update(tmp_path: Path) -> None:
    store = ArtifactStore()
    artifact_path = tmp_path / "repo.md"

    doc = ArtifactDocument(
        frontmatter={
            "id": "repo-1",
            "name": "repo",
            "root": "/tmp/repo",
            "default_branch": "main",
            "status": "active",
            "commands": {},
            "unknown": "keep-me",
        },
        body="# Repo\n",
    )

    store.write(artifact_path, doc)
    loaded = store.read(artifact_path)

    assert loaded.frontmatter["unknown"] == "keep-me"
    assert loaded.body == "# Repo\n"

    updated = store.update(
        artifact_path,
        frontmatter_updates={"status": "archived"},
        body="# Repo Updated\n",
    )

    assert updated.frontmatter["status"] == "archived"
    assert updated.frontmatter["unknown"] == "keep-me"
    assert updated.body == "# Repo Updated\n"
