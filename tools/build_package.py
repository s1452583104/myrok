"""把仓库打成可以发给别人的绿色 zip 包。

做的事，按顺序：

1. **前置检查** —— `models/detect.onnx` 存在（没有就提示先跑 export_onnx.py）、
   manifest.yaml 里每一张模板 PNG 都在、onnxruntime/pyinstaller 可导入。
   这些错在构建前发现只要一秒，等 PyInstaller 跑完三分钟再发现就是浪费。
2. **PyInstaller** —— `rok-assistant.spec`（onedir）。
3. **产物断言** —— 必需的资源都在（templates/manifest.yaml、config.example.yaml、
   配置说明.md、
   models/detect.onnx、_internal 下的 onnxruntime 与 rapidocr 模型）；
   **训练数据一个都不能有**（dataset/、runs/、imgs/、raw_imgs/、tools/、tests/、
   *.pt、torch）。体积失控基本都是从这儿漏进去的。
4. **打 zip** —— `dist/rok-assistant-<version>-win64.zip`，打印体积和顶层清单。

用法（仓库根目录）：
    .venv/Scripts/python.exe -X utf8 tools/build_package.py
    .venv/Scripts/python.exe -X utf8 tools/build_package.py --skip-build   # 只校验已有产物
    .venv/Scripts/python.exe -X utf8 tools/build_package.py --no-zip
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SPEC = ROOT / "rok-assistant.spec"
DIST = ROOT / "dist"
APP_DIR = DIST / "rok-assistant"
ONNX = ROOT / "models" / "detect.onnx"

# 解压后必须存在的资源（相对 _internal/，即 sys._MEIPASS）
REQUIRED_RESOURCES = [
    "templates/manifest.yaml",
    "config.example.yaml",
    "models/detect.onnx",
    "README-用户.txt",
    "配置说明.md",          # README-用户.txt 直接指到它，缺了用户就找不到
    "onnxruntime",
    "rapidocr_onnxruntime/models",
]

# 顶层（app 目录与 _internal）绝不允许出现的名字。
# 只查顶层：第三方包内部自带同名子目录（onnxruntime/tools、shapely/tests、
# onnxruntime/datasets 的示例 .onnx）都是正常的，深搜会把它们误判成泄漏。
FORBIDDEN_TOP = {
    "dataset": "训练数据集",
    "runs": "训练输出",
    "imgs": "原始截图",
    "raw_imgs": "待标注截图",
    "recordings": "运行截图",
    "logs": "运行日志",
    "src": "源码目录",
    "tests": "测试代码",
    "tools": "开发工具脚本",
    "torch": "torch（excludes 没挡住）",
    "torchvision": "torchvision（excludes 没挡住）",
    "ultralytics": "ultralytics（excludes 没挡住）",
    "paddle": "paddle（excludes 没挡住）",
    "paddlex": "paddlex（excludes 没挡住）",
}

# 体积红线：正常 ~330MB。torch 溜进来会直接翻到 4GB，用它当兜底哨兵。
MAX_BYTES = 500 * 1e6


def _read_version() -> str:
    """从 pyproject.toml 读 version，避免版本号两处维护。"""
    try:
        import tomllib
        with open(ROOT / "pyproject.toml", "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except Exception:
        return "0.0.0"


def _preflight() -> int:
    print("=== 前置检查 ===")
    problems = []

    if not ONNX.is_file():
        problems.append(f"缺少 {ONNX.relative_to(ROOT)} —— 先跑："
                        f" .venv/Scripts/python.exe -X utf8 tools/export_onnx.py")
    else:
        print(f"  OK  {ONNX.relative_to(ROOT)}  ({ONNX.stat().st_size / 1e6:.1f} MB)")

    # manifest 里引用的模板文件必须都在，否则打包出来是"能启动但认不出东西"，
    # 现场很难查。（直接读 yaml 而不是 TemplateRegistry：registry 没有暴露
    # 条目列表，为构建脚本加个公开属性不值当。）
    try:
        import yaml
        manifest = ROOT / "templates" / "manifest.yaml"
        raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        entries = raw.get("templates", [])
        missing = [e["file"] for e in entries
                   if not (manifest.parent / e["file"]).is_file()]
        if missing:
            problems.append(f"{len(missing)} 张模板文件缺失，例如 {missing[:3]}")
        else:
            print(f"  OK  templates/manifest.yaml 引用的 {len(entries)} 张模板齐全")
    except Exception as e:
        problems.append(f"模板清单加载失败：{e}")

    for mod in ("onnxruntime", "PyInstaller"):
        try:
            __import__(mod)
            print(f"  OK  {mod} 可导入")
        except ImportError:
            problems.append(f"{mod} 未安装（pip install -e '.[build]'）")

    if problems:
        print("\n前置检查未通过：")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    return 0


def _run_pyinstaller() -> int:
    print("\n=== PyInstaller ===")
    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm",
           "--distpath", str(DIST), "--workpath", str(ROOT / "build")]
    print("  " + " ".join(cmd))
    t0 = time.time()
    r = subprocess.run(cmd, cwd=str(ROOT))
    print(f"  退出码 {r.returncode}，耗时 {time.time() - t0:.0f}s")
    return r.returncode


def _verify(app_dir: Path) -> int:
    print("\n=== 产物校验 ===")
    if not app_dir.is_dir():
        print(f"  ✗ 产物目录不存在：{app_dir}")
        return 1

    internal = app_dir / "_internal"
    base = internal if internal.is_dir() else app_dir

    problems = []
    for rel in REQUIRED_RESOURCES:
        p = base / rel
        if p.exists():
            print(f"  OK  {rel}")
        else:
            problems.append(f"缺少资源 {rel}")

    # 顶层泄漏扫描
    for root in (app_dir, base):
        if not root.is_dir():
            continue
        for child in root.iterdir():
            why = FORBIDDEN_TOP.get(child.name)
            if why:
                problems.append(f"包里混进了{why}：{child.relative_to(app_dir)}")

    # 权重文件：.pt 一个都不该有（我们只发 .onnx）。
    # .onnx 不查全盘——onnxruntime 自带 datasets/*.onnx 示例。
    pts = [p for p in app_dir.rglob("*.pt") if p.is_file()]
    if pts:
        problems.append(f"包里混进了 {len(pts)} 个 .pt 权重，例如 "
                        f"{pts[0].relative_to(app_dir)}")

    exe = app_dir / "rok-assistant.exe"
    if exe.is_file():
        print(f"  OK  rok-assistant.exe ({exe.stat().st_size / 1e6:.1f} MB)")
    else:
        problems.append("缺少 rok-assistant.exe")

    total = sum(f.stat().st_size for f in app_dir.rglob("*") if f.is_file())
    print(f"  体积合计 {total / 1e6:.0f} MB")
    if total > MAX_BYTES:
        problems.append(f"体积 {total / 1e6:.0f} MB 超过红线 {MAX_BYTES / 1e6:.0f} MB，"
                        f"大概率是 torch 之类被打了进来")

    if problems:
        print("\n产物校验未通过：")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    return 0


def _make_zip(app_dir: Path, version: str) -> Path:
    print("\n=== 打 zip ===")
    out = DIST / f"rok-assistant-v{version}-win64.zip"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(app_dir.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(app_dir.parent))
    print(f"  {out.relative_to(ROOT)}  ({out.stat().st_size / 1e6:.0f} MB)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="打绿色 zip 发行包")
    ap.add_argument("--skip-build", action="store_true",
                    help="跳过 PyInstaller，只校验 dist/rok-assistant 现有产物")
    ap.add_argument("--no-zip", action="store_true", help="只构建，不打 zip")
    args = ap.parse_args()

    if not args.skip_build:
        rc = _preflight()
        if rc:
            return rc
        rc = _run_pyinstaller()
        if rc:
            return rc

    rc = _verify(APP_DIR)
    if rc:
        return rc

    version = _read_version()
    if args.no_zip:
        print(f"\n完成（未打 zip）：{APP_DIR}")
        return 0
    out = _make_zip(APP_DIR, version)
    print(f"\n完成：{out}")
    print("解压后双击 rok-assistant.exe；首启会自动生成 config.yaml 并探测 MuMu 路径。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
