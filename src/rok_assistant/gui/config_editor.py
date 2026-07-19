from __future__ import annotations
from pathlib import Path
import tempfile
from PyQt6.QtWidgets import QPlainTextEdit
from pydantic import ValidationError
from rok_assistant.infra.config import load_config

class ConfigEditor(QPlainTextEdit):
    def __init__(self, config_path: Path):
        super().__init__()
        self._path = config_path
        self.setPlainText(config_path.read_text(encoding="utf-8"))

    def save(self) -> bool:
        text = self.toPlainText()
        # Validate the current text by writing to temp + loading
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                         delete=False, encoding="utf-8") as f:
            f.write(text)
            tmp = Path(f.name)
        try:
            load_config(tmp)
        except ValidationError as e:
            # Show in parent statusBar if available; fall back silently
            try:
                self.parent().statusBar().showMessage(f"Invalid config: {e}")
            except Exception:
                pass
            return False
        finally:
            try:
                tmp.unlink()
            except Exception:
                pass
        self._path.write_text(text, encoding="utf-8")
        return True
