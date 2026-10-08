"""全局测试隔离：把授权门面换成「存储指向 tmp_path、指纹固定」的替身。

**必须 autouse**：`tests/integration/test_gui_smoke.py` 每条用例都新建
`MainWindow`，而 `MainWindow` 会读授权状态。不隔离的话，跑一次测试就会往
开发机的注册表与 `C:\\ProgramData` 里写试用记录，而且每条用例写一次
（spec §8.2）。

顺带也避免每条用例都跑一次 1~2s 的 WMI。
"""
from __future__ import annotations

import time

import pytest

from rok_assistant.infra.licensing import fingerprint as fp_mod
from rok_assistant.infra.licensing import guard as guard_mod
from rok_assistant.infra.licensing import store as store_mod

TEST_FP = bytes(range(32))


@pytest.fixture(autouse=True)
def _isolated_license_guard(tmp_path):
    fp = fp_mod.Fingerprint(fp_main=TEST_FP,
                            machine_code=fp_mod.machine_code_from(TEST_FP),
                            degraded=False, reason="测试固定指纹")
    st = store_mod.Store(store_mod.Locations(
        registry=None,
        # 文件名**刻意和 licensing/conftest.py 的 make_guard 不一样**：
        # 两者共用同一个 tmp_path，同名文件会互相覆盖。
        program_data=tmp_path / "_auto" / "license.dat",
        user_file=tmp_path / ".roklicense_auto"))
    now = int(time.time())
    guard_mod._set_guard_for_tests(guard_mod.Guard(st, fp, clock=lambda: now))
    yield
    guard_mod._set_guard_for_tests(None)
