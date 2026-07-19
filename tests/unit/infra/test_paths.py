from pathlib import Path
from rok_assistant.infra.paths import ProjectPaths

def test_project_paths_creates_dirs(tmp_path):
    p = ProjectPaths(root=tmp_path)
    p.ensure_dirs()
    assert p.log_dir.exists()
    assert p.template_dir.exists()
    assert p.recording_dir.exists()

def test_project_paths_manifest_yaml():
    p = ProjectPaths(root=Path("/tmp"))
    assert p.manifest_path.name == "manifest.yaml"
