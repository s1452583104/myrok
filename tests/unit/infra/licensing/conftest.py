import base64
import pathlib

import pytest

from rok_assistant.infra.licensing import codec, verify

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
