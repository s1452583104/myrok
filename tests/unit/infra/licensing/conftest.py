import base64
import pathlib
import time

import pytest

from rok_assistant.infra.licensing import codec, verify
from rok_assistant.infra.licensing import fingerprint as fp_mod
from rok_assistant.infra.licensing import guard as guard_mod
from rok_assistant.infra.licensing import store as store_mod

_FIXTURES = pathlib.Path(__file__).resolve().parents[3] / "fixtures" / "licensing"


@pytest.fixture(scope="session")
def test_private_seed() -> bytes:
    return base64.b64decode(
        (_FIXTURES / "test_private.key").read_text(encoding="ascii").strip())


@pytest.fixture(scope="session")
def test_public_b64() -> str:
    return (_FIXTURES / "test_public.b64").read_text(encoding="ascii").strip()


@pytest.fixture(scope="session")
def sign_code(test_private_seed):
    """返回 `make(fp_main, *, kind, days=0, serial=1, fp6=None) -> str`。

    `fp6` 用来故意签一个「绑定到别的机器」的码（跨机器用例）。
    """
    def _make(fp_main, *, kind, days=0, serial=1, fp6=None):
        payload = codec.build_payload(ver=codec.FORMAT_VERSION,
                                      fp_main=fp6 if fp6 is not None else fp_main,
                                      kind=kind, days=days, serial=serial)
        return codec.encode_code(payload,
                                 verify.sign_payload(payload, test_private_seed))
    return _make


FP = bytes(range(32))
DAY = 86400


@pytest.fixture
def base_time() -> int:
    """真实当前时间。

    **不要用写死的时间戳**：存储文件的 mtime 是真实时间，拿一个 2023 年的
    假时钟去跑，`Guard._mtime_in_future` 会把「mtime 在未来」误判成篡改。
    """
    return int(time.time())


@pytest.fixture
def make_guard(tmp_path, base_time, test_public_b64):
    """返回 `make(fp_main=FP, clock=None, locations=None, public_key_b64=...) -> Guard`。

    不传 `clock` 时用 `base_time`；同一个用例里多次调用会共享同一份
    `tmp_path` 存储，所以可以造出「换一个 Guard 重读同一份记录」的现场。

    `public_key_b64` 默认注入**测试公钥**：`sign_code` 用测试私钥签码，而
    Guard 生产默认用内嵌 shipped 公钥，两者不同——不注入的话凡用 `sign_code`
    的用例都会 BAD_SIG。
    """
    def _make(*, fp_main=FP, clock=None, locations=None,
              public_key_b64=test_public_b64):
        fp = fp_mod.Fingerprint(fp_main=fp_main,
                                machine_code=fp_mod.machine_code_from(fp_main),
                                degraded=False, reason="测试固定指纹")
        st = store_mod.Store(locations or store_mod.Locations(
            registry=None,
            program_data=tmp_path / "pd" / "license.dat",
            user_file=tmp_path / ".roklicense"))
        return guard_mod.Guard(st, fp, clock=clock or (lambda: base_time),
                               public_key_b64=public_key_b64)
    return _make
