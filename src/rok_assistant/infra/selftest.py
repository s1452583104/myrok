"""自检：验证「当前这份程序能不能跑」——尤其是打包后的绿色包。

存在的理由：绿色包最大的失败模式是**解压到别人机器上才发现缺东西**
（ONNX 权重没打进去、onnxruntime 的 DLL 被漏掉、rapidocr 的模型不在、
模板路径没按 resource_dir 解开）。这些在开发机上永远复现不了，因为
开发机 `import cv2` 走的是 venv。

所以在 launcher 里挂一个 `--selftest`：冻结后的 exe 跑一遍真实的识别
链路（读模板 → 装识别器 → 拿一帧喂 YOLO → 跑 OCR），把结果写到
`logs/selftest.log` 并打印。目标机器上解压后跑一次就知道包好不好。

用法：
    绿色包：  rok-assistant.exe --selftest
    源码：    .venv/Scripts/python.exe -X utf8 -m rok_assistant.infra.selftest

退出码 0 = 全部通过；非 0 = 有 FAIL，日志里有原因。
"""
from __future__ import annotations

import base64
import sys
import time
import traceback
from pathlib import Path


def _run_checks() -> list[tuple[str, bool, str]]:
    """返回 [(检查项, 是否通过, 详情)]。每项独立捕获异常，一项挂不影响其它项。"""
    import numpy as np

    from .app_paths import resource_dir, user_dir

    results: list[tuple[str, bool, str]] = []

    def check(name: str):
        def deco(fn):
            t0 = time.time()
            try:
                detail = fn() or ""
                ok = True
            except Exception as e:
                detail = f"{type(e).__name__}: {e}"
                ok = False
            results.append((name, ok, f"{detail}  [{time.time() - t0:.2f}s]"))
            return fn
        return deco

    @check("目录解析")
    def _():
        return f"resource_dir={resource_dir()}  user_dir={user_dir()}  frozen={getattr(sys, 'frozen', False)}"

    @check("cv2 导入 + 图像解码")
    def _():
        import cv2
        # 造一张 8x8 的 PNG 走完整的编码/解码往返——imdecode 才是识别链路
        # 真正用的（cv2.imread 在中文路径下会静默返回 None）。
        png = cv2.imencode(".png", np.zeros((8, 8, 3), dtype=np.uint8))[1]
        img = cv2.imdecode(png, cv2.IMREAD_COLOR)
        assert img is not None and img.shape == (8, 8, 3), f"解码结果异常 {img}"
        return f"cv2 {cv2.__version__}，解码往返 OK"

    @check("onnxruntime 导入 + provider")
    def _():
        import onnxruntime as ort
        provs = ort.get_available_providers()
        assert "CPUExecutionProvider" in provs, f"没有 CPU provider：{provs}"
        return f"{ort.__version__} {provs}"

    @check("检测模型加载 + 一帧推理")
    def _():
        from ..core.recognizers.onnx_detect import OnnxYoloModel
        model_path = resource_dir() / "models" / "detect.onnx"
        assert model_path.is_file(), f"缺模型文件 {model_path}"
        model = OnnxYoloModel(model_path)
        n_cls = len(model.names)
        assert n_cls > 0, "模型元数据里没有类别名"
        # 一帧全黑 1920x1080：不指望检出东西，只要求整条链路跑通不炸
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        t0 = time.time()
        res = model(frame, verbose=False)
        dt = (time.time() - t0) * 1000
        n_box = len(res[0].boxes)
        assert dt < 2000, f"单帧推理 {dt:.0f}ms，慢得不像话"
        return f"{n_cls} 类，全黑帧检出 {n_box} 框，耗时 {dt:.0f}ms"

    @check("模板清单加载 + 识别器装配")
    def _():
        from ..core.template_registry import TemplateRegistry
        manifest = resource_dir() / "templates" / "manifest.yaml"
        assert manifest.is_file(), f"缺模板清单 {manifest}"
        reg = TemplateRegistry.load(manifest)
        recs = reg.build_recognizers(
            yolo_model=resource_dir() / "models" / "detect.onnx",
            ocr_fallback=True)
        assert recs, "识别器字典为空"
        return f"{len(recs)} 个识别器"

    @check("rapidocr 导入 + 模型就位")
    def _():
        import rapidocr_onnxruntime as _r
        from rapidocr_onnxruntime import RapidOCR  # noqa: F401
        # 模型在 wheel 内的 rapidocr_onnxruntime/models/。冻结后 collect_all
        # 会把它放到 _internal 下，所以先看 resource_dir()，源码运行则回落到
        # 包自己的安装位置。
        candidates = [resource_dir() / "rapidocr_onnxruntime" / "models",
                      Path(_r.__file__).resolve().parent / "models"]
        model_dir = next((c for c in candidates if c.is_dir()), None)
        assert model_dir is not None, f"找不到 OCR 模型目录，试过 {candidates}"
        onnx_files = sorted(p.name for p in model_dir.glob("*.onnx"))
        assert onnx_files, f"OCR 模型目录里没有 .onnx：{model_dir}"
        return f"{model_dir} 下 {len(onnx_files)} 个模型 {onnx_files[:3]}"

    @check("PyQt6 导入")
    def _():
        from PyQt6.QtCore import QT_VERSION_STR
        from PyQt6.QtWidgets import QApplication  # noqa: F401
        return f"Qt {QT_VERSION_STR}"

    @check("首启配置文件")
    def _():
        from .app_paths import ensure_user_files
        from ..infra.config import RootConfig
        import yaml
        cfg = ensure_user_files()
        if not cfg.is_file():
            return f"未生成 {cfg}（资源里没有 config.example.yaml？）"
        RootConfig.model_validate(yaml.safe_load(cfg.read_text(encoding="utf-8")))
        return f"{cfg} 通过校验"

    @check("写权限")
    def _():
        d = user_dir() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return f"{d} 可写"

    @check("MuMu 连接诊断（只诊断，不判定）")
    def _():
        """跑一次真实的 MuMuManager 查询，把耗时/返回码/环境记下来。

        **故意不用 6s 的正式超时**：用户报「无法运行 MuMuManager」时最需要知道的
        就是「到底跑了多久」——用同一个 6s 去测只会复现同一个超时，问不出新东西。
        这里给 20s，超了才算真的卡死。

        不判定成败：MuMu 没装、没开都不算包有问题，所以一律返回 PASS + 诊断文本。
        """
        import os

        from .mumu import detect_mumu_paths
        from .subproc import run as run_child

        mgr = (detect_mumu_paths() or {}).get("mumu_manager_path") or ""
        meipass = getattr(sys, "_MEIPASS", "") or ""
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        bits = [
            f"frozen={getattr(sys, 'frozen', False)}",
            f"cwd={os.getcwd()}",
            f"QT_* 变量={sorted(k for k in os.environ if k.startswith('QT_')) or '无'}",
            f"_MEIPASS 混进 PATH={bool(meipass) and any(meipass.lower() in p.lower() for p in path_entries)}",
        ]
        if not mgr:
            bits.append("没探测到 MuMuManager 路径")
            return "；".join(bits)
        bits.append(f"MuMuManager={mgr}")
        for args in (["info", "-v", "all"], ["info", "-v", "0"]):
            t0 = time.time()
            try:
                p = run_child([mgr, *args], capture_output=True, timeout=20)
                err = p.stderr[:120].decode(errors="replace").strip()
                bits.append(f"{' '.join(args)}: rc={p.returncode} "
                            f"{time.time() - t0:.2f}s {len(p.stdout)}B"
                            + (f" stderr={err}" if err else ""))
            except Exception as e:
                bits.append(f"{' '.join(args)}: {type(e).__name__} "
                            f"{time.time() - t0:.2f}s {e}")
        return "；".join(bits)

    @check("各模拟器连接（只诊断，不判定）")
    def _():
        """照 config.yaml 里每个模拟器各连一次、各截一帧。

        **存在的理由**：2026-10-05 用户报「点 Start 后只连上一个，另一个报错」，
        但运行日志里两个 worker 都正常跑到待机、没有任何异常——说明失败发生在
        `create_handle_source` 阶段（在 worker 起来之前），日志里看不到。而这
        一段**只有打包后才会出问题**（冻结进程起子进程慢、环境不同），开发机上
        怎么试都是好的。所以让绿色包自己能回答「哪一台连不上、报什么错」。

        与「MuMu 连接诊断」同理：模拟器没开、配置没填都不算包有缺陷，
        一律 PASS，把事实写进诊断文本。
        """
        import time

        import yaml

        from .app_paths import user_dir
        from ..core.handle_source import create_handle_source

        cfg_path = user_dir() / "config.yaml"
        if not cfg_path.is_file():
            return f"没有 {cfg_path}，跳过"
        try:
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            return f"{cfg_path} 读不出来: {type(e).__name__}: {e}"

        app = cfg.get("app") or {}
        instances = cfg.get("instances") or []
        if not instances:
            return f"{cfg_path} 里没有 instances"

        bits = []
        for inst in instances:
            label = inst.get("id") or inst.get("name") or "?"
            t0 = time.time()
            try:
                handle = create_handle_source(
                    mumu_index=inst.get("mumu_index"),
                    mumu_manager_path=app.get("mumu_manager_path", ""),
                    adb_address=inst.get("adb_address", "") or "",
                    adb_path=app.get("adb_path", "adb"),
                    window_title_pattern=inst.get("window_title_pattern", "") or "")
                frame = handle.capture()
                bits.append(f"{label}: OK {frame.shape} {time.time() - t0:.2f}s")
            except Exception as e:
                # 连不上的**完整**原因就在这里——用户报的「另一个实例报错」
                # 十有八九是这一行，别只写类型名。
                bits.append(f"{label}: {type(e).__name__}: {e} "
                            f"[{time.time() - t0:.2f}s]")
        return "；".join(bits)

    @check("授权状态与机器码")
    def _():
        return _license_status_detail()

    @check("授权链自检")
    def _():
        return _license_chain_detail()

    return results


def _license_status_detail() -> str:
    """打印授权状态 + 机器码——用户报障时直接抄这一行给作者。

    **不做拦截**：它是诊断工具，被授权挡住反而查不了问题（spec §8.3）。
    """
    from .licensing import guard
    st = guard.current_guard().status()
    return (f"状态={st.kind} 剩余={st.days_left} 到期={st.expiry} "
            f"机器码={st.machine_code}")


def _license_chain_detail() -> str:
    """授权链自检：`cryptography` 能否导入、内嵌公钥能否加载、签名往返。

    这一项是给**冻结包**兜底的——`cryptography` 有 C 扩展，是本次唯一新增的
    二进制依赖，绿色包最容易在这里缺东西，而缺了的表现是「所有激活码都
    无效」，极难远程排查（spec §8.3）。
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    from .licensing import codec, verify

    priv = Ed25519PrivateKey.generate()
    pub_b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode("ascii")
    payload = codec.build_payload(ver=codec.FORMAT_VERSION,
                                  fp_main=b"\x01" * 32,
                                  kind=codec.KIND_EXTEND, days=1, serial=1)
    code = codec.encode_code(payload, priv.sign(payload))
    got, reason = verify.verify_code(code, b"\x01" * 32, public_key_b64=pub_b64)
    assert got is not None, f"签名往返失败：{reason}"
    assert codec.serial_of(code) == 1, "码解析不回 serial"
    verify.load_public_key()          # 真发码用的那把也必须能加载
    return f"cryptography OK，签名往返 OK，内嵌公钥可加载（码长 {len(code)}）"


def run() -> int:
    from .app_paths import user_dir

    # 冻结后 console=False，但从终端跑 --selftest 时 stdout 是 GBK 控制台，
    # 中文会变成乱码。日志文件本身是 UTF-8 不受影响，这里只是让终端也可读。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    print("=" * 60)
    print("rok-assistant 自检")
    print("=" * 60)
    results = _run_checks()

    n_fail = 0
    lines = []
    for name, ok, detail in results:
        tag = "PASS" if ok else "FAIL"
        line = f"[{tag}] {name}：{detail}"
        lines.append(line)
        print(line)
        if not ok:
            n_fail += 1

    summary = f"{len(results) - n_fail}/{len(results)} 通过"
    print("-" * 60)
    print(summary if not n_fail else f"{summary}，有 {n_fail} 项失败")

    # 落盘一份：绿色包是 console=False，用户看不到 stdout，得留证据
    try:
        out = user_dir() / "logs" / "selftest.log"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + f"\n\n{summary}\n", encoding="utf-8")
        print(f"结果已写入 {out}")
    except OSError:
        traceback.print_exc()

    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(run())
