import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # 无头跑 Qt：必须在 import Qt 之前

import pathlib
import sys

import pytest
from PyQt6.QtWidgets import QApplication

# tools/ 不在 pythonpath 里，按路径挂进去（tools/*.py 之间用兄弟模块 import）
_TOOLS = pathlib.Path(__file__).resolve().parents[4] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.append(str(_TOOLS))

import license_tool                                        # noqa: E402

from rok_assistant.infra.licensing import (                # noqa: E402
    codec,
    fingerprint,
    verify,
)

FP = bytes(range(32))


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def machine_code():
    return fingerprint.machine_code_from(FP)


def test_machine_code_roundtrips_to_first_10_bytes(machine_code):
    assert license_tool.machine_code_to_fp_main(machine_code) == FP[:10]


def test_machine_code_with_typo_is_rejected():
    """抄错一位的机器码必须当场拦住——否则会发出一个永远激活不了的码。

    改的是**主体**的一位而不是校验位：校验位是主体的函数，主体变了它必然
    对不上，所以这条用例是确定失败，不会因为撞上某个巧合值而偶发通过。
    """
    body = codec.clean_input(fingerprint.machine_code_from(FP))
    typo = ("B" if body[0] != "B" else "C") + body[1:]
    bad = f"{typo[:4]}-{typo[4:8]}-{typo[8:12]}-{typo[12:16]}-{body[16]}"
    with pytest.raises(ValueError):
        license_tool.machine_code_to_fp_main(bad)


def test_issued_code_verifies_on_target_machine(machine_code, test_private_seed,
                                                test_public_b64):
    """端到端：工具发出来的码，客户端能验通过。"""
    item = license_tool.issue(machine_code, kind=codec.KIND_EXTEND, days=30,
                              serial=1, seed=test_private_seed)
    payload, reason = verify.verify_code(item.code, FP, test_public_b64)
    assert reason is None
    assert payload["days"] == 30
    assert payload["serial"] == 1


def test_issued_code_is_bound_to_that_machine(machine_code, test_private_seed,
                                              test_public_b64):
    item = license_tool.issue(machine_code, kind=codec.KIND_EXTEND, days=30,
                              serial=1, seed=test_private_seed)
    _, reason = verify.verify_code(item.code, bytes(range(100, 132)),
                                   test_public_b64)
    assert reason == verify.REASON_WRONG_MACHINE


def test_issued_code_is_formatted_in_groups(machine_code, test_private_seed):
    item = license_tool.issue(machine_code, kind=codec.KIND_PERMANENT, days=0,
                              serial=1, seed=test_private_seed)
    # 122 字符按 5 分组 → 25 组、24 个连字符（最后一组只有 2 个字符）。
    # 不是 122 // 5 = 24 组。
    groups = item.code.split("-")
    assert len(groups) == -(-codec.CODE_CHARS // codec.GROUP_SIZE)     # 25
    assert len(groups[-1]) == codec.CODE_CHARS % codec.GROUP_SIZE      # 2
    assert all(len(g) == codec.GROUP_SIZE for g in groups[:-1])


def test_next_serial_continues_from_ledger(tmp_path):
    ledger = tmp_path / "issued.csv"
    assert license_tool.next_serial(license_tool.read_ledger(ledger)) == 1
    for serial in (1, 2, 5):
        license_tool.append_ledger(
            ledger,
            license_tool.Issued(serial=serial, kind=codec.KIND_EXTEND,
                                days=1, code="X"),
            "AAAA-BBBB-CCCC-DDDD-E")
    assert license_tool.next_serial(license_tool.read_ledger(ledger)) == 6


def test_ledger_roundtrip(tmp_path):
    ledger = tmp_path / "issued.csv"
    license_tool.append_ledger(
        ledger,
        license_tool.Issued(serial=1, kind=codec.KIND_PERMANENT, days=0,
                            code="CODE1"),
        "AAAA-BBBB-CCCC-DDDD-E")
    license_tool.append_ledger(
        ledger,
        license_tool.Issued(serial=2, kind=codec.KIND_EXTEND, days=30,
                            code="CODE2"),
        "AAAA-BBBB-CCCC-DDDD-E")
    rows = license_tool.read_ledger(ledger)
    assert [r["serial"] for r in rows] == ["1", "2"]
    assert rows[0]["kind"] == "permanent"
    assert rows[1]["days"] == "30"


def test_read_ledger_tolerates_missing_file(tmp_path):
    assert license_tool.read_ledger(tmp_path / "nope.csv") == []


def test_used_serials_rejects_malformed_row():
    """畸形行**必须报错**，不能静默跳过。

    被跳过的若正好是当前最大号，`next_serial` 就会回退，把已卖出的号再发一次
    ——客户机会以「该激活码已被使用」拒掉作者刚发的码。
    """
    rows = [{"serial": "1"}, {"serial": ""}, {"serial": "3"}]
    with pytest.raises(ValueError) as ei:
        license_tool.used_serials(rows)
    assert "第 3 行" in str(ei.value)     # 表头算第 1 行，坏行是第 3 行


def test_append_ledger_writes_header_into_empty_existing_file(tmp_path):
    """已存在但 0 字节的台账（touch 出来、或上次写失败留下的）也要补表头。

    否则 DictReader 把首行数据当表头，serial 列整个丢掉。
    """
    ledger = tmp_path / "issued.csv"
    ledger.touch()                                    # 0 字节
    license_tool.append_ledger(
        ledger,
        license_tool.Issued(serial=7, kind=codec.KIND_EXTEND, days=1, code="X"),
        "AAAA-BBBB-CCCC-DDDD-E")
    rows = license_tool.read_ledger(ledger)
    assert len(rows) == 1
    assert rows[0]["serial"] == "7"


def test_on_issue_does_not_let_exceptions_escape(qapp, monkeypatch, tmp_path,
                                                 test_private_seed):
    """槽里逃逸的异常会让 PyQt6 调 qFatal：整个工具 abort、刚发的码一起丢。"""
    def boom(*_a, **_k):
        raise OSError("台账被占用")
    monkeypatch.setattr(license_tool, "LEDGER", tmp_path / "issued.csv")
    monkeypatch.setattr(license_tool, "append_ledger", boom)
    monkeypatch.setattr(license_tool.QMessageBox, "critical",
                        staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(license_tool.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: None))
    win = license_tool.LicenseTool(test_private_seed)
    win.machine_edit.setText(fingerprint.machine_code_from(FP))
    win._on_issue()                                   # 不得抛出


def test_on_issue_clears_stale_code_when_machine_code_is_bad(
        qapp, monkeypatch, tmp_path, test_private_seed):
    """机器码有误时清掉上一次的码，否则用户可能复制到错的那个。"""
    monkeypatch.setattr(license_tool, "LEDGER", tmp_path / "issued.csv")
    monkeypatch.setattr(license_tool.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: None))
    win = license_tool.LicenseTool(test_private_seed)
    win.code_view.setPlainText("OLD-CODE")
    good = fingerprint.machine_code_from(FP)
    win.machine_edit.setText(good[:-1] + ("A" if good[-1] != "A" else "B"))
    win._on_issue()
    assert win.code_view.toPlainText() == ""
