"""激活对话框：机器码（等宽 + 复制）、激活码输入、结果提示。"""
from __future__ import annotations

from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ..infra.logger import get_logger

logger = get_logger(__name__)


class LicenseDialog(QDialog):
    def __init__(self, guard, parent=None):
        super().__init__(parent)
        self._guard = guard
        self.setWindowTitle("激活")
        self.resize(600, 320)
        self._build_ui()
        self._refresh_status()

    def _build_ui(self):
        root = QVBoxLayout(self)
        form = QFormLayout()

        self.machine_code_edit = QLineEdit(self._guard.machine_code())
        self.machine_code_edit.setReadOnly(True)
        # 等宽字体：机器码靠用户手抄或截图转述，等宽能显著降低抄错率
        self.machine_code_edit.setFont(QFont("Consolas", 11))
        copy_btn = QPushButton("复制")
        copy_btn.clicked.connect(self._copy_machine_code)
        row = QHBoxLayout()
        row.addWidget(self.machine_code_edit)
        row.addWidget(copy_btn)
        form.addRow("机器码", row)

        # 激活码 122 字符，用多行框 + 等宽字体，粘贴时自动折行
        self.code_edit = QPlainTextEdit()
        self.code_edit.setFont(QFont("Consolas", 10))
        self.code_edit.setPlaceholderText("粘贴激活码（连字符可有可无）")
        form.addRow("激活码", self.code_edit)

        root.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        buttons = QDialogButtonBox()
        # 用 ActionRole 而不是 AcceptRole：AcceptRole 会自动 accept 关窗，
        # 激活失败时用户就得重新打开对话框再贴一次码。
        self.activate_btn = buttons.addButton(
            "激活", QDialogButtonBox.ButtonRole.ActionRole)
        self.activate_btn.clicked.connect(self._on_activate)
        buttons.addButton("关闭", QDialogButtonBox.ButtonRole.RejectRole)
        root.addWidget(buttons)

    def _copy_machine_code(self):
        QGuiApplication.clipboard().setText(self.machine_code_edit.text())
        self.status_label.setText("机器码已复制")

    def _refresh_status(self):
        """读不出状态也必须能开窗——这里是授权出问题时**唯一**的自救入口。

        异常逃出 Qt 槽 → PyQt6 默认 qFatal → 整个进程 abort（与 _license_ok
        同一类；那个已经兜住了，这里不能漏）。
        """
        try:
            text = self._guard.status().label()
        except Exception:                      # noqa: BLE001 - 授权坏了也得能开窗自救
            logger.exception("读取授权状态失败")
            text = "授权状态未知"
        self.status_label.setText(f"当前状态：{text}")

    def _on_activate(self):
        try:
            ok, message = self._guard.activate(self.code_edit.toPlainText())
        except Exception:                      # noqa: BLE001 - 异常逃出 Qt 槽 = 进程 abort
            logger.exception("激活失败")
            ok = False
            message = "激活失败：授权组件异常，请把 --selftest 的输出发给作者"
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            "color:#27ae60;" if ok else "color:#c0392b;")
        if ok:
            self.accept()
