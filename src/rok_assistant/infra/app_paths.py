"""应用根目录解析 —— 让同一份代码在「源码运行」和「PyInstaller 冻结」下都能找到文件。

为什么需要：`src/` 里所有路径原本都是 CWD 相对的（`config.yaml`、`templates/`、
`logs/`、`recordings/`），只在「从仓库根目录启动」时成立。绿色包解压到任意
目录、双击 exe 时 CWD 可能是 `C:\\Windows\\System32`，全部会找不到。

两种根目录要分开：

- **resource_dir()** —— 只读资源，PyInstaller 的 `datas` 落点。onedir 模式下是
  `<exe目录>/_internal`（即 `sys._MEIPASS`），放 `templates/`、`models/detect.onnx`、
  `config.example.yaml`。
- **user_dir()** —— 可写数据，exe 同级目录，放 `config.yaml`、`logs/`、`recordings/`。
  用户要能看到和编辑它们，所以不能塞进 `_internal`。
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

_DEV_ROOT = Path(__file__).resolve().parents[3]   # src/rok_assistant/infra/ -> 仓库根


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_base_dir() -> Path:
    """exe 所在目录（冻结）/ 仓库根（源码运行）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _DEV_ROOT


def resource_dir() -> Path:
    """只读资源根。冻结时是 PyInstaller 的 _internal（sys._MEIPASS）。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_base_dir()))
    return _DEV_ROOT


def user_dir() -> Path:
    """可写数据根（config.yaml / logs / recordings 的家）。"""
    return app_base_dir()


def resolve_asset(path, base: Path | None = None) -> Path:
    """把配置里的相对路径按资源根解开；绝对路径原样返回。"""
    p = Path(path)
    if p.is_absolute():
        return p
    return (base if base is not None else resource_dir()) / p


def config_path() -> Path:
    return user_dir() / "config.yaml"


def ensure_user_files() -> Path:
    """首启：没有 config.yaml 就从 config.example.yaml 复制一份，并填入探测到的
    MuMu/adb 路径。**已存在则绝不改动**——用户可能手改过，重写会毁掉注释和格式。

    返回 config.yaml 的路径。
    """
    from .logger import get_logger
    logger = get_logger(__name__)

    cfg = config_path()
    if cfg.exists():
        return cfg

    seed = resource_dir() / "config.example.yaml"
    if not seed.is_file():
        logger.error("找不到配置模板 %s，无法生成 config.yaml", seed)
        return cfg

    shutil.copyfile(seed, cfg)
    logger.info("首次运行：已从 %s 生成 %s", seed, cfg)
    print(f"[首启] 已生成配置文件：{cfg}")

    _fill_detected_paths(cfg, logger)
    return cfg


def _fill_detected_paths(cfg: Path, logger) -> None:
    """把探测到的 MuMu/adb 路径写进刚生成的 config.yaml（只填空字段）。

    走**逐行文本替换**而不是 `yaml.safe_load` → `safe_dump` 往返：后者会把
    `config.example.yaml` 里的全部注释和空行抹掉。那份注释是这个文件唯一的
    说明书（`target_levels` 怎么排序、`role` 有哪三种、哪些字段互斥），
    首启就被吃掉的话新用户只能对着光秃秃的键值猜。
    """
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        logger.exception("生成 config.yaml 后读回失败，跳过路径探测")
        return

    from .mumu import detect_mumu_paths
    found = detect_mumu_paths()

    changed = []
    for key in ("mumu_manager_path", "adb_path"):
        value = found.get(key)
        if not value:
            continue
        # 只认「值为空」的行：`key: ""` / `key: ''` / `key:`
        pat = re.compile(rf'^([ \t]*{key}:[ \t]*)(?:""|\'\')?[ \t]*$', re.MULTILINE)
        if not pat.search(text):
            continue    # 已填过值，不动
        # Windows 路径里的反斜杠在双引号 YAML 里会被当转义（\M 非法），
        # 单引号才是字面量——只需把内部的 ' 写成 ''。
        literal = "'" + value.replace("'", "''") + "'"
        text = pat.sub(lambda m: m.group(1) + literal, text, count=1)
        changed.append(f"{key}={value}")

    if not changed:
        print("[首启] 没探测到 MuMu 安装位置，请在「⚙ 配置」里手动填写")
        return
    try:
        cfg.write_text(text, encoding="utf-8")
        logger.info("首启自动填入：%s", "，".join(changed))
        print(f"[首启] 已自动填入：{'，'.join(changed)}")
    except OSError:
        logger.exception("写回探测到的路径失败")
