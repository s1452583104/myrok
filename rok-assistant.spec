# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir 绿色包）。

用 `tools/build_package.py` 调用，不要直接 `pyinstaller rok-assistant.spec`
——构建脚本会先做前置检查（ONNX 权重存在、manifest 里每张模板都在），
再在产物上断言资源齐全且没混进训练数据。

体积控制的核心是 excludes：venv 里 torch(+cu128) 约 4GB，是 ultralytics 的
传递依赖。生产推理走 onnxruntime，见 src/rok_assistant/core/recognizers/onnx_detect.py。
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve()

# ---- 随包分发的只读资源 ----
# onedir 模式下这些会落到 <exe目录>/_internal/，运行时由 infra/app_paths.py 的
# resource_dir()（即 sys._MEIPASS）定位。
datas = [
    (str(ROOT / "templates"), "templates"),          # manifest.yaml + 模板 PNG
    (str(ROOT / "config.example.yaml"), "."),        # 首启生成 config.yaml 的种子
    (str(ROOT / "models" / "detect.onnx"), "models"),
    (str(ROOT / "packaging" / "README-用户.txt"), "."),
    # 面向非程序员的配置说明；README-用户.txt 里直接指到它，所以必须随包走
    (str(ROOT / "docs" / "配置说明.md"), "."),
]

binaries = []
hiddenimports = []

# ---- 两个包必须 collect_all，静态分析抓不全 ----
# 1) rapidocr_onnxruntime：OCR 模型（ch_PP-OCRv3_*_infer.onnx）和默认配置 yaml
#    在 wheel 的数据目录里；且 RapidOCR 是函数内懒 import（ocr_text.py），
#    PyInstaller 扫不到。
# 2) onnxruntime：capi 下的 .pyd + provider DLL（onnxruntime_providers_*.dll）
#    是二进制，只有 collect_all 会带上。
for _pkg in ("rapidocr_onnxruntime", "onnxruntime", "pyclipper", "shapely"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h


# ---- 瘦身：剔掉确定用不到的大件 ----
# 必须在 Analysis **之后** 过滤：cv2 的那两个 ffmpeg DLL 不是 collect_all
# 带进来的，是 PyInstaller 自带的 hook-cv2 在 Analysis 里加的，前面拦不住。
# TOC 条目格式是 (包内相对路径, 源路径, 类型)，按第一个元素匹配。
#
# opencv 的 videoio ffmpeg 解码器合计 55MB：我们只做 imread/imdecode/
# imwrite/imencode 与模板匹配，从不读视频。这两个是 delay-load，删掉不影响
# import cv2 / imdecode（已由 tools/build_package.py 后的 --selftest 验证）。
_DROP_BIN = ("opencv_videoio_ffmpeg",)
# 第三方包自带的、跟运行无关的目录：onnxruntime 的模型转换脚本和示例模型、
# shapely 的测试。
_DROP_DATA = ("onnxruntime/tools/", "onnxruntime/datasets/", "shapely/tests/")

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 训练 / 导出专用：进包就是 4GB
        "torch", "torchvision", "ultralytics", "onnx",
        # OCR 的旧 paddle 后端（生产走 rapidocr，见 ocr_text.py）
        "paddle", "paddleocr", "paddlex",
        # 科学计算栈：没被生产代码 import，多半是某个依赖的可选分支
        "matplotlib", "pandas", "scipy", "numpy.f2py", "IPython",
        # 测试与开发工具
        "pytest", "pytestqt", "setuptools", "pip",
        # 别把 Tk 拖进来（PyQt6 应用）
        "tkinter", "_tkinter",
    ],
    noarchive=False,
    optimize=0,
)

def _drop(toc, frags):
    """按包内相对路径（TOC 第 0 项）过滤，Windows 上反斜杠先归一。"""
    out = []
    for e in toc:
        dest = str(e[0]).replace("\\", "/")
        if not any(f in dest for f in frags):
            out.append(e)
    return out


_before = len(a.binaries) + len(a.datas)
a.binaries = _drop(a.binaries, _DROP_BIN)
a.datas = _drop(a.datas, _DROP_DATA)
print(f"[spec] 瘦身：剔除 {_before - len(a.binaries) - len(a.datas)} 个文件条目")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="rok-assistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # upx 压过的 onnxruntime DLL 有加载失败的报告，不值这个体积
    console=False,      # GUI 程序，不留黑窗；崩溃写 logs/startup_crash.log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="rok-assistant",
)
