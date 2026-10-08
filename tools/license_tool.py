"""发码工具：机器码 → 激活码。**不进发行包。**

用法（注意 -X utf8，控制台是 GBK）：
    .venv/Scripts/python.exe -X utf8 tools/license_tool.py

首启（`secrets/license_private.key` 不存在）会生成密钥对，并把公钥写进
`src/rok_assistant/infra/licensing/pubkey.py`——**记得提交它**。

私钥丢了不影响已发出的码（公钥没变），但**没法再发新码**。跑完请备份。
"""
from __future__ import annotations

import base64
import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from gen_license_keypair import (            # noqa: E402
    DEFAULT_KEY,
    DEFAULT_PUB,
    write_keypair,
)
from rok_assistant.infra.licensing import codec, fingerprint, verify  # noqa: E402

from PyQt6.QtGui import QFont, QGuiApplication  # noqa: E402
from PyQt6.QtWidgets import (                   # noqa: E402
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

LEDGER = ROOT / "secrets" / "issued.csv"
LEDGER_FIELDS = ["issued_at", "machine_code", "kind", "days", "serial", "code"]


@dataclass(frozen=True)
class Issued:
    serial: int
    kind: int
    days: int
    code: str


# ---------------- 纯逻辑（可单测，不碰 Qt） ----------------

def machine_code_to_fp_main(machine_code: str) -> bytes:
    """机器码 → 10 字节。激活码只绑前 6 字节，所以不需要完整 32 字节指纹。

    校验位不过就抛 `ValueError`——发码前拦住抄错的机器码，否则会发出一个
    **永远激活不了**的码，来回一轮就是一次售后（spec §9）。
    """
    clean = codec.clean_input(machine_code)
    if not fingerprint.is_valid_machine_code(clean):
        raise ValueError("机器码校验位不对：请让用户重新抄一遍（共 17 位，"
                         "最后一组是校验位）")
    return codec.b32decode_nopad(clean[:16])


def issue(machine_code: str, *, kind: int, days: int, serial: int,
          seed: bytes) -> Issued:
    payload = codec.build_payload(ver=codec.FORMAT_VERSION,
                                  fp_main=machine_code_to_fp_main(machine_code),
                                  kind=kind, days=days, serial=serial)
    code = codec.encode_code(payload, verify.sign_payload(payload, seed))
    return Issued(serial=serial, kind=kind, days=days,
                  code=codec.format_code(code))


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def used_serials(rows: list[dict]) -> set[int]:
    """已用过的 serial 集合。

    畸形行**必须报错，不能静默跳过**：被跳过的若正好是当前最大号，
    `next_serial` 就会回退，把已卖出的号再发一次——客户机上 `check_code`
    会以「该激活码已被使用」拒掉作者刚发的码，来回一轮就是一次售后。
    """
    out: set[int] = set()
    for lineno, row in enumerate(rows, start=2):   # 第 1 行是表头
        try:
            out.add(int(row["serial"]))
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(
                f"台账第 {lineno} 行的 serial 读不出来（{row.get('serial')!r}）："
                f"先修好这一行再发码，否则会重发已用过的号") from e
    return out


def next_serial(rows: list[dict]) -> int:
    used = used_serials(rows)
    return max(used) + 1 if used else 1


def append_ledger(path: Path, item: Issued, machine_code: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 空文件（touch 出来的、或上次写失败留下的 0 字节）也要补表头，
    # 否则首行数据会被 DictReader 当成表头，serial 列整个丢掉。
    fresh = not path.exists() or path.stat().st_size == 0
    # 不用 utf-8-sig：追加模式下每次都会再写一个 BOM，把文件写坏
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        if fresh:
            writer.writeheader()
        writer.writerow({
            "issued_at": datetime.now().isoformat(timespec="seconds"),
            "machine_code": machine_code,
            "kind": ("permanent" if item.kind == codec.KIND_PERMANENT
                     else "extend"),
            "days": item.days,
            "serial": item.serial,
            "code": item.code,
        })


# ---------------- 界面 ----------------

class LicenseTool(QWidget):
    def __init__(self, seed: bytes):
        super().__init__()
        self._seed = seed
        self.setWindowTitle("RoK 助手 · 发码工具")
        self.resize(720, 460)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        form = QFormLayout()

        self.machine_edit = QLineEdit()
        self.machine_edit.setFont(QFont("Consolas", 11))
        self.machine_edit.setPlaceholderText("XXXX-XXXX-XXXX-XXXX-C")
        form.addRow("机器码", self.machine_edit)

        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["延长 N 天", "永久授权"])
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        form.addRow("类型", self.kind_combo)

        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 65535)          # payload 里 days 是 2 字节
        self.days_spin.setValue(30)
        form.addRow("天数", self.days_spin)

        root.addLayout(form)

        self.issue_btn = QPushButton("生成激活码")
        self.issue_btn.clicked.connect(self._on_issue)
        root.addWidget(self.issue_btn)

        self.code_view = QPlainTextEdit()
        self.code_view.setReadOnly(True)
        self.code_view.setFont(QFont("Consolas", 10))
        root.addWidget(self.code_view)

        row = QHBoxLayout()
        copy_btn = QPushButton("复制激活码")
        copy_btn.clicked.connect(self._copy)
        row.addWidget(copy_btn)
        root.addLayout(row)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self._refresh_status()

    def _refresh_status(self, extra: str = ""):
        try:
            issued = len(read_ledger(LEDGER))
            text = f"台账：{LEDGER}（已发 {issued} 条）"
        except Exception:                      # noqa: BLE001 - 异常逃出 Qt 槽 = 进程 abort
            text = f"台账读取失败：{LEDGER}"
        self.status_label.setText(f"{extra}\n{text}" if extra else text)

    def _on_kind_changed(self, index: int):
        self.days_spin.setEnabled(index == 0)      # 永久不需要天数

    def _on_issue(self):
        """任何异常都**不许**逃出这个槽：PyQt6 对槽里逃逸的异常调 qFatal，
        整个发码工具直接 abort——连错误框都不弹，刚发的码也一起丢。"""
        try:
            self._issue_once()
        except Exception as e:                 # noqa: BLE001 - 见 docstring
            self.code_view.clear()
            QMessageBox.critical(self, "发码失败", str(e))
            self._refresh_status("发码失败，未写台账")

    def _issue_once(self):
        permanent = self.kind_combo.currentIndex() == 1
        kind = codec.KIND_PERMANENT if permanent else codec.KIND_EXTEND
        days = 0 if permanent else self.days_spin.value()
        machine_code = codec.clean_input(self.machine_edit.text())
        serial = next_serial(read_ledger(LEDGER))
        try:
            item = issue(machine_code, kind=kind, days=days, serial=serial,
                         seed=self._seed)
        except ValueError as e:
            self.code_view.clear()             # 别把上一次的码留在屏幕上
            QMessageBox.warning(self, "机器码有问题", str(e))
            return
        append_ledger(LEDGER, item, machine_code)
        self.code_view.setPlainText(item.code)
        what = "永久" if permanent else f"{days} 天"
        self._refresh_status(f"已发第 {serial} 号（{what}）")

    def _copy(self):
        text = self.code_view.toPlainText()
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        self._refresh_status("激活码已复制")


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    if not DEFAULT_KEY.exists():
        answer = QMessageBox.question(
            None, "首次运行",
            f"没找到私钥：\n{DEFAULT_KEY}\n\n"
            "现在生成一对新密钥，并把公钥写进 pubkey.py（**记得提交它**）。\n"
            "私钥请务必备份——丢了就没法再发新码（已发出的码不受影响）。\n\n继续？")
        if answer != QMessageBox.StandardButton.Yes:
            return 1
        write_keypair(DEFAULT_KEY, DEFAULT_PUB)
        QMessageBox.information(
            None, "已生成密钥对",
            f"公钥已写入：\n{DEFAULT_PUB}\n请提交它。\n\n"
            f"私钥：\n{DEFAULT_KEY}\n请备份。")
    seed = base64.b64decode(DEFAULT_KEY.read_text(encoding="ascii").strip())
    win = LicenseTool(seed)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
