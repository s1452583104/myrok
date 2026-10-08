"""生成 Ed25519 授权密钥对：私钥写 secrets/，公钥写进 pubkey.py。

用法（注意 -X utf8，控制台是 GBK）：
    .venv/Scripts/python.exe -X utf8 tools/gen_license_keypair.py

幂等：私钥已存在时**复用它**、只重写 pubkey.py（用于「公钥文件丢了但私钥还在」）。
真要换新密钥对加 `--force`——那会让**已发出的激活码全部失效**，别随手用。

私钥丢了不影响已发的码（公钥没变），但**没法再发新码**。跑完请备份。
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEY = ROOT / "secrets" / "license_private.key"
DEFAULT_PUB = ROOT / "src" / "rok_assistant" / "infra" / "licensing" / "pubkey.py"

_PUB_TEMPLATE = '''"""内嵌公钥——**生成物，请勿手改**。

由 `tools/gen_license_keypair.py` 写出。改了它，所有已发出的激活码当场失效。
"""
from __future__ import annotations

PUBLIC_KEY_B64 = "{b64}"
'''


def write_keypair(key_path: Path, pub_module: Path, *,
                  force_new: bool = False) -> str:
    """写出密钥对，返回公钥 base64。

    私钥已存在且未指定 force_new 时**复用**它——这是「pubkey.py 丢了、
    私钥还在」的恢复路径，比重新生成安全得多。
    """
    if key_path.exists() and not force_new:
        seed = base64.b64decode(key_path.read_text(encoding="ascii").strip())
        priv = Ed25519PrivateKey.from_private_bytes(seed)
    else:
        priv = Ed25519PrivateKey.generate()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(
            base64.b64encode(priv.private_bytes_raw()).decode("ascii"),
            encoding="ascii")

    b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode("ascii")
    pub_module.parent.mkdir(parents=True, exist_ok=True)
    pub_module.write_text(_PUB_TEMPLATE.format(b64=b64), encoding="utf-8")
    return b64


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 Ed25519 授权密钥对")
    ap.add_argument("--key", type=Path, default=DEFAULT_KEY)
    ap.add_argument("--pub", type=Path, default=DEFAULT_PUB)
    ap.add_argument("--force", action="store_true",
                    help="强制生成新密钥对（已发出的激活码会全部失效）")
    a = ap.parse_args(argv)

    existed = a.key.exists()
    if existed and a.force:
        print("[警告] --force：将生成**新**密钥对，旧公钥签发的激活码全部失效")
    b64 = write_keypair(a.key, a.pub, force_new=a.force)
    print(f"[OK] 私钥 {a.key}（**务必备份**：丢了就没法再发新码）")
    print(f"[OK] 公钥 {a.pub}（请提交它）")
    print(f"     公钥 base64：{b64}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
