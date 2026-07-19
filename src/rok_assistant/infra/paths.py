from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    @property
    def log_dir(self) -> Path: return self.root / "logs"
    @property
    def template_dir(self) -> Path: return self.root / "templates"
    @property
    def recording_dir(self) -> Path: return self.root / "recordings"
    @property
    def manifest_path(self) -> Path: return self.template_dir / "manifest.yaml"

    def ensure_dirs(self) -> None:
        for d in (self.log_dir, self.template_dir, self.recording_dir):
            d.mkdir(parents=True, exist_ok=True)
