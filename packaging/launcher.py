"""PyInstaller 入口脚本。

为什么不直接拿 `src/rok_assistant/gui/main_window.py` 当入口：它内部用的是相对
导入（`from .character_card import ...`），只有在「作为包的一部分被导入」时才成立；
PyInstaller 把入口脚本当顶层脚本分析，相对导入会直接 ImportError。

所以这里只做两件事：源码运行时把 `src/` 挂上 `sys.path`，然后调用真正的 main()。
冻结运行时 `rok_assistant` 已被打进包，不需要（也不能）挂 path。
"""
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    _SRC = Path(__file__).resolve().parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))

from rok_assistant.gui.main_window import main   # noqa: E402

if __name__ == "__main__":
    # --selftest：不开窗口，跑一遍真实识别链路并打印结果（见 infra/selftest.py）。
    # 绿色包在目标机器上解压后先跑这个，比"双击看它炸不炸"靠谱得多。
    if "--selftest" in sys.argv:
        from rok_assistant.infra.selftest import run
        sys.exit(run())
    main()
