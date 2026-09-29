# -*- coding: utf-8 -*-
"""Ingest hand-recorded screenshots (raw_imgs/<scene>/) into the YOLO dataset.

**增量入库**：只往 `dataset/` 里加东西，绝不重跑 `tools/auto_label_yolo.py`，
绝不重新生成 `dataset/dataset.yaml`。原因：现有 dataset.yaml 是手工维护的 63 类，
而 auto_label 会从 manifest 的 53 个模板重建（去掉 3 个 --exclude 后只有 50 类），
且它用截断写重写 train.txt/val.txt，会丢掉 63 条手工追加的 manual* 帧。

预标注三层（都是「起点」，入库后仍需人工复核 overlay 修正）：

1. **模板匹配** — 复用 `tools/auto_label_yolo.py:multi_match()`（贪心多匹配 + zero-out
   NMS），覆盖 manifest 里有模板的类。
2. **文本锚定** — `zhaizi_level_text` 的框就是「等级: N」文本自身的框，且该框横向随
   位数漂移（cx 标准差 0.0645）、纵向很稳（cy 0.4918±0.0052）：在稳定 y 的 ROI 内跑
   RapidOCR，取「等级」所在行合并后的 BBox 作标注框。
3. **门控位置先验** — 无模板但位置稳的类用实测中位数放固定框。**必须门控**，否则会在
   不该出现的帧上造出假框（例：`sort_opt_*` 只在排序下拉**展开**时存在，收起时同一
   文本出现在顶部选择条上）。门控用 OCR 文本 + 纵向位置容差。

用法（仓库根目录）：
    .venv/Scripts/python.exe tools/ingest_raw_imgs.py --dry-run   # 只看覆盖报告
    .venv/Scripts/python.exe tools/ingest_raw_imgs.py             # 正式入库
    .venv/Scripts/python.exe tools/ingest_raw_imgs.py --force     # 覆盖已入库帧的标注
"""
from __future__ import annotations

import argparse
import hashlib
import os
import random
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

from auto_label_yolo import multi_match  # noqa: E402
from class_names_zh import zh  # noqa: E402
from rok_assistant.core.template_registry import TemplateRegistry  # noqa: E402

NATIVE_W, NATIVE_H = 1920, 1080
VAL_RATIO = 0.1
SEED = 42  # 与 auto_label_yolo 同种子，保证 val 划分可复现

# 场景 → 该页面**预期出现**的类（用于覆盖报告：预期有却没有框 = 漏标，需人工补）。
# 划分依据：对现有 623 张已标注帧按来源前缀实测各前缀的类分布反推，非臆测。
SCENES: dict[str, dict] = {
    "01_zhaizi_search": {
        "desc": "野蛮人/城寨搜索页",
        "classes": ["search_icon", "level_minus", "level_plus", "search_btn",
                    "search_back", "tab_fortress", "toast_no_fortress",
                    "barb_search_tab", "zhaizi_level_text"],
    },
    "02_warlist": {
        "desc": "战争列表（集结）",
        "classes": ["war_title", "sort_selector", "sort_opt_latest",
                    "sort_opt_nearest", "sort_opt_shortest", "join_btn",
                    "rally_attack_popup", "time_5min", "red_rally", "blue_rally",
                    "queue_battle_icon"],
    },
    "03_queue_panel": {
        "desc": "队列栏五态图标",
        "classes": ["queue_panel", "queue_badge", "queue_gather_icon",
                    "queue_march_icon", "queue_flag_icon", "queue_battle_icon",
                    "queue_return_icon", "queue_fight_icon"],
    },
    "04_march_preset": {
        "desc": "行军编队预设 + 兵种",
        "classes": ["selected_preset_1", "selected_preset_2", "selected_preset_3",
                    "selected_preset_4", "selected_preset_5", "selected_preset_6",
                    "preset_1", "preset_2", "preset_3", "preset_4", "preset_5",
                    "preset_6", "troop_infantry", "troop_cavalry", "troop_archer",
                    "troop_siege", "troop_check", "form_title", "march_btn",
                    "join_create_btn", "swap_btn", "replace_popup"],
    },
    "05_char_settings": {
        "desc": "设置/角色管理",
        "classes": ["settings_btn", "settings_title", "profile_title",
                    "char_mgmt_btn", "char_mgmt_title", "char_avatar_lszz",
                    "char_avatar_lswk", "switch_confirm_yes", "click_to_enter",
                    "menu_expanded"],
    },
    "06_home_map": {
        "desc": "主界面/地图/联盟",
        "classes": ["map_btn", "alliance_btn", "menu_expanded", "warning_panel",
                    "red_rally", "blue_rally", "rally_attack_popup"],
    },
    "07_ap_refill": {
        "desc": "行动力补充",
        "classes": ["ap_refill"],
    },
    "99_unsorted": {
        "desc": "未分类（入库时归位）",
        "classes": [],
    },
}

# 文本锚定：框 = 该文本自身的框。ROI 用 (x1, y1, x2, y2) 绝对像素，取足够宽松的范围。
# zhaizi_level_text 实测 cy 0.4918±0.0052（n=12），横向放宽到 0.02~0.50 覆盖位数漂移。
TEXT_ANCHORED: dict[str, dict] = {
    "zhaizi_level_text": {
        "text": "等级",
        "roi": (40, 460, 960, 610),
        "merge_line": True,   # 与同一行右侧的「N」块合并成整条「等级: N」
    },
}

# 门控位置先验：固定框 + 必须满足的门控条件。所有坐标是 1920x1080 归一化 (cx, cy, w, h)。
# gate_text   = 该文本必须被 OCR 找到，且其纵向中心与 prior 的 cy 相差不超过 gate_dy；
# gate_not_tmpl = 该模板**不得**命中（负向门控，排除同名不同义的 UI）。
#
# 刻意**不含** `sort_opt_latest/nearest/shortest`：实测那 12 个实例里有一半来自
# 162x279 等**裁剪图**（标注左边界恒为 0.0000、宽 0.47~0.50，是相对裁剪的坐标），
# 与整屏不是一个坐标系；且整屏那半边的三种选项行还有互相重叠的约定。加先验只会
# 再叠第 4 种约定。这三类请人工标，或先统一既有标注约定。
#
# 同样不含 `selected_preset_*`（x 有两组取值 0.8625/0.775，且既有标注互相差一行）
# 与 `troop_check`（是 4 列网格，不是单点）。
PRIORS: list[dict] = [
    {
        # 实测 n=12：cx 0.2901±0.0023 / cy 0.3319±0.0088（极稳）。
        # 负向门控必需：`tab_fortress` 与 `barb_search_tab` 实测是**同一个矩形**
        # （cx 0.2909/0.2891、w 0.1443/0.1406）且从不共存——语义是「当前激活的
        # 页签」。不加门控会在城寨页帧上放出野蛮人页签的假框，等于拿同一片像素
        # 教两个类。
        "cls": "barb_search_tab",
        "box": (0.2891, 0.3292, 0.1406, 0.0509),
        "roi": (300, 300, 900, 420),
        "gate_text": "野蛮人",
        "gate_dy": 0.05,
        "gate_not_tmpl": "tab_fortress",
    },
]

# 场景 → 需要跑模板匹配的 manifest 模板 id 白名单（None = 全部）。
# 限定白名单能显著减少误报（例：队列图标模板不该在搜索页上匹配）。
SCENE_TEMPLATES: dict[str, list[str] | None] = {
    "01_zhaizi_search": ["search_icon", "level_minus", "level_plus", "search_btn",
                         "search_back", "tab_fortress", "toast_no_fortress"],
    "02_warlist": ["war_title", "join_btn", "rally_attack_popup", "time_5min",
                   "red_rally", "blue_rally", "queue_battle_icon"],
    "03_queue_panel": ["queue_panel", "queue_badge", "queue_gather_icon",
                       "queue_march_icon", "queue_flag_icon", "queue_battle_icon",
                       "queue_return_icon", "queue_fight_icon", "queue_recall_icon"],
    "04_march_preset": ["march_btn", "preset_1", "preset_2", "preset_3", "preset_4",
                        "preset_5", "preset_6", "troop_infantry", "troop_cavalry",
                        "troop_archer", "troop_siege", "form_title", "join_create_btn",
                        "swap_btn", "replace_popup", "ap_refill"],
    "05_char_settings": ["settings_btn", "settings_title", "profile_title",
                         "char_mgmt_btn", "char_mgmt_title", "char_avatar_lszz",
                         "char_avatar_lswk", "switch_confirm_yes", "click_to_enter",
                         "menu_expanded"],
    "06_home_map": ["map_btn", "alliance_btn", "menu_expanded", "warning_panel",
                    "red_rally", "blue_rally", "rally_attack_popup"],
    "07_ap_refill": ["ap_refill"],
    "99_unsorted": None,
}


class _Ocr:
    """懒加载 RapidOCR（导入 + 首次推理都很慢，dry-run 空跑时不该付这个成本）。"""

    def __init__(self) -> None:
        self._eng = None

    def text_blocks(self, img: np.ndarray, roi: tuple[int, int, int, int]):
        """ROI 内 OCR，返回 [(x1, y1, x2, y2, text, conf)]（绝对像素）。"""
        if self._eng is None:
            from rok_assistant.core.recognizers.ocr_text import RapidOcrEngine
            self._eng = RapidOcrEngine()
        h, w = img.shape[:2]
        x1, y1, x2, y2 = roi
        crop = img[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        if crop.size == 0:
            return []
        ox, oy = max(0, x1), max(0, y1)
        return [(b.x1 + ox, b.y1 + oy, b.x2 + ox, b.y2 + oy, t, c)
                for b, t, c in self._eng.detect_text(crop)]


def _find_text(blocks, needle: str):
    """含 needle 的文本块里取置信度最高的一个。"""
    hits = [b for b in blocks if needle in b[4]]
    return max(hits, key=lambda b: b[5]) if hits else None


# 同行合并的最大水平间隙（像素）。相对锚点行高取，下限 16px 兜住矮行。
# 这不是调参：`等级：` 与紧跟的 `N` 之间是**零间隙或几个像素**（同一段文字被
# DBNet 切成两块），而下面那条提示语离它有 350px 远。没有这个上界时，RapidOCR
# 把「等级：3 您的城市附近暂未找到符合条」切成的两块会被无差别合并，产出
# 286~802px 的宽框——2026-09-24 实测该类 50 条标注里 17 条是这么来的，直接
# 导致 1~6 级全部检不出（紧框 95px vs 宽框 800px，YOLO 只能回归到折中）。
MERGE_GAP_FACTOR = 1.0
MERGE_GAP_MIN = 16.0


def _merge_line(blocks, anchor):
    """把 anchor 与同一行**紧邻**的文本块合并成一条（「等级:」+「10」→「等级: 10」）。

    只合并水平间隙不超过 `max(锚点行高, MERGE_GAP_MIN)` 的块，见上面常量注释。
    """
    ax1, ay1, ax2, ay2 = anchor[:4]
    ah = ay2 - ay1
    gap_max = max(ah * MERGE_GAP_FACTOR, MERGE_GAP_MIN)
    x1, y1, x2, y2 = ax1, ay1, ax2, ay2
    for b in blocks:
        if b is anchor:
            continue
        bx1, by1, bx2, by2 = b[:4]
        cy = (by1 + by2) / 2
        if not (ay1 - ah * 0.5 <= cy <= ay2 + ah * 0.5):
            continue
        gap = max(bx1 - ax2, ax1 - bx2, 0.0)   # 左右两侧都算，重叠时为 0
        if gap > gap_max:
            continue
        x1, y1 = min(x1, bx1), min(y1, by1)
        x2, y2 = max(x2, bx2), max(y2, by2)
    return x1, y1, x2, y2


def prelabel(img: np.ndarray, scene: str, names_inv: dict[str, int],
             templates: dict[str, np.ndarray], specs: dict, ocr: _Ocr,
             use_roi: bool = True
             ) -> tuple[list[tuple[int, float, float, float, float]], list[str],
                        dict[str, dict[str, float]]]:
    """三层预标注。返回 ([(cid, cx, cy, w, h)] 归一化, [来源说明], 分数统计)。

    `use_roi=True`（默认）模板只在 manifest 的 ROI 内搜。ROI 不是可有可无的优化，是
    误报闸门：实测放开全帧后 `preset_1..6` 在 44x44 的模板下互相串位（6 个预设槽全长一个
    样，每个模板在整列都过 0.90 阈值），958/1918 个新框落到本类 ROI 之外。要全帧搜传
    `use_roi=False`（`--full-frame`），但务必逐类核对越界框。

    代价是 ROI 按某一版 UI 硬编码，弹窗一移位就整类静默归零。所以对 ROI 内 0 命中的
    模板**额外算一次全帧分数**（只记分、不入框），让报告能区分「真没目标」和「ROI 错位」。
    统计字典 = {"best": {tid: ROI 内最高分}, "best_full": {tid: 全帧最高分(仅 0 命中时)}}。
    """
    h, w = img.shape[:2]
    out: list[tuple[int, float, float, float, float]] = []
    prov: list[str] = []
    best_scores: dict[str, float] = {}
    best_full: dict[str, float] = {}
    # 去重键含类 id：同**一个类**被两层命中（如模板 + 先验）只留先到的；
    # 不同类落在同一框上**不**去重——那是状态判断错了（tab_fortress/barb_search_tab
    # 这种互斥同形 UI），必须让两个框都露出来被覆盖报告看见，而不是静默吞掉后一个。
    seen: set[tuple[int, int, int, int, int]] = set()

    def _add(cls: str, x1: float, y1: float, x2: float, y2: float, src: str) -> None:
        cid = names_inv.get(cls)
        if cid is None:  # 类不在 dataset.yaml（模板比数据集新）→ 跳过，绝不改类表
            return
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 - x1 < 2 or y2 - y1 < 2:
            return
        key = (cid, int(x1), int(y1), int(x2), int(y2))
        if key in seen:
            return
        seen.add(key)
        out.append((cid, (x1 + x2) / 2 / w, (y1 + y2) / 2 / h,
                    (x2 - x1) / w, (y2 - y1) / h))
        prov.append(f"{cls}<-{src}")

    # --- 1) 模板匹配 ---
    allow = SCENE_TEMPLATES.get(scene)
    for tid, tmpl in templates.items():
        if allow is not None and tid not in allow:
            continue
        if tid not in names_inv:
            continue
        spec = specs[tid]
        roi = None
        if use_roi and not spec.roi.is_full:
            roi = (spec.roi.x1, spec.roi.y1, spec.roi.x2, spec.roi.y2)
        matches, best = multi_match(img, tmpl, spec.threshold, roi)
        best_scores[tid] = max(best_scores.get(tid, 0.0), best)
        if not matches and roi is not None:
            # ROI 内 0 命中：再算一次全帧分数，**只记分不入框**。分数高 = ROI 错位（该
            # 补 ROI 或人工补框），分数低 = 这帧真没这个元素。不区分的话都只看到「0 框」。
            _, full = multi_match(img, tmpl, 1.0, None)
            best_full[tid] = max(best_full.get(tid, 0.0), full)
        for m in matches:
            x1, y1, x2, y2 = m["bbox"]
            _add(tid, x1, y1, x2, y2, "tmpl")

    # --- 2) 文本锚定 ---
    for cls, spec in TEXT_ANCHORED.items():
        if cls not in names_inv:
            continue
        blocks = ocr.text_blocks(img, spec["roi"])
        anchor = _find_text(blocks, spec["text"])
        if anchor is None:
            continue
        box = _merge_line(blocks, anchor) if spec.get("merge_line") else anchor[:4]
        _add(cls, *box, "ocr")

    # --- 3) 门控位置先验 ---
    for p in PRIORS:
        cls = p["cls"]
        if cls not in names_inv:
            continue
        blocks = ocr.text_blocks(img, p["roi"])
        anchor = _find_text(blocks, p["gate_text"])
        if anchor is None:
            continue  # 门控未过：该 UI 状态不在这帧上，绝不硬放框
        cx_n, cy_n, w_n, h_n = p["box"]
        cy_ocr = (anchor[1] + anchor[3]) / 2 / h
        if abs(cy_ocr - cy_n) > p["gate_dy"]:
            continue  # 文本在别处（如收起的排序条）→ 状态不符

        blocker = p.get("gate_not_tmpl")
        if blocker and blocker in templates:
            # threshold 传 1.0：只要 best_score，不要 matches
            _, bbest = multi_match(img, templates[blocker], 1.0, p["roi"])
            if bbest >= 0.85:
                continue  # 该区域是另一个同形 UI（城寨页签）→ 状态不符

        x1 = (cx_n - w_n / 2) * w
        y1 = (cy_n - h_n / 2) * h
        _add(cls, x1, y1, x1 + w_n * w, y1 + h_n * h, "prior")

    return out, prov, {"best": best_scores, "best_full": best_full}


def _load_dataset_yaml(path: Path):
    """读 dataset.yaml（只读！）。返回 (names: id->name, names_inv: name->id)。"""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    names = {int(k): str(v) for k, v in raw["names"].items()}
    return names, {v: k for k, v in names.items()}


def _read_list(path: Path) -> list[str]:
    """读路径清单，忽略空行。"""
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _merge_split(list_path: Path, new_paths: list[str],
                 taken: list[str] = ()) -> tuple[int, list[str]]:
    """把新图路径增量并入 train.txt/val.txt（读-合并-重写，绝不截断）。

    `taken` 是**另一个** split 现有的行。必须传：`--force` 重跑时 val 抽样的随机流会
    偏移（0 框帧不消耗随机数，帧集合一变后续抽签全变），同一帧可能这次抽进 val、上次
    已在 train——不拦就是同帧既训练又验证（实测漏了 44 行）。帧一旦分好就不再搬家。

    返回 (新增条数, 该文件最终行列表)。已存在的路径不重复追加——幂等。
    """
    existing = _read_list(list_path)
    # Windows 路径大小写不敏感：按小写比对，避免同一文件以不同大小写重复入库
    have = {p.lower() for p in existing}
    other = {p.lower() for p in taken}
    added = [p for p in new_paths if p.lower() not in have and p.lower() not in other]
    return len(added), existing + added


def _prune_split(lines: list[str]) -> tuple[list[str], int]:
    """摘掉指向已不存在图像的路径行。

    `--force` 重跑后某帧可能从「有框」变成「0 框」，此时它的硬链接已被撤掉；如果
    train/val 里还留着那一行，ultralytics 会按缺失文件报警甚至中断训练。
    只处理绝对路径行（现有文件全是绝对路径），相对路径行原样保留，不做猜测。
    """
    kept = [ln for ln in lines if not os.path.isabs(ln) or Path(ln).exists()]
    return kept, len(lines) - len(kept)


# --- 内容级去重（孪生帧）---------------------------------------------------

def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _index_images(images_dir: Path) -> dict[str, str]:
    """已入库帧的内容索引：md5 -> 帧名。

    同内容取**名字最小**的那份（`sorted` + `setdefault`），让结果可复现——
    否则「孪生帧报的是哪个名字」会随目录遍历顺序漂。
    """
    idx: dict[str, str] = {}
    for p in sorted(images_dir.glob("*.png")):
        idx.setdefault(_md5(p), p.stem)
    return idx


def _twin_of(digest: str, ingested: dict[str, str], flat: str) -> str | None:
    """`flat` 是否有逐字节相同的**已入库**帧；没有则 None。

    同名帧不算孪生——那是「这帧已经入过库」，由调用方的 `link.exists()` 报，
    报成「与已入库 X 相同」只会让人以为存在两个文件。
    """
    twin = ingested.get(digest)
    if twin is None or twin == Path(flat).stem:
        return None
    return twin


def _orphans(images_dir: Path, split_lines: list[str]) -> list[str]:
    """有图、却不在任何 split 里的帧名（按路径比对，不是按文件名）。

    train/val 里两种路径形态并存（老帧指向 recordings/，入库帧指向 dataset/images/），
    所以只能比 resolved 路径。孤儿帧不报错、不告警，只是**静默地不参与训练**——
    这正是它值得一道显式检查的原因。
    """
    have = {os.path.normcase(str(Path(ln).resolve())) for ln in split_lines}
    return sorted(p.name for p in images_dir.glob("*.png")
                  if os.path.normcase(str(p.resolve())) not in have)


def _print_skips(skipped: list[str], no_box: list[str]) -> None:
    if skipped:
        print(f"\n跳过 {len(skipped)} 帧：")
        for s in skipped[:10]:
            print(f"  - {s}")
        if len(skipped) > 10:
            print(f"  ...（共 {len(skipped)}）")
    if no_box:
        print(f"\n0 框未入库 {len(no_box)} 帧（复核 logs/review/ 确认是几何错位还是真负样本）：")
        for s in no_box[:10]:
            print(f"  - {s}")
        if len(no_box) > 10:
            print(f"  ...（共 {len(no_box)}）")


def _write_list(path: Path, lines: list[str]) -> None:
    """原子写路径清单（.tmp + os.replace），保留末尾换行。

    ultralytics 只对 `./` 前缀的行按 txt 所在目录解析，裸相对路径会按 CWD 解析——
    所以这里原样保留既有行的文本（现有文件是绝对路径），不做任何规整。
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _render(img: np.ndarray, boxes, names: dict, prov: list[str], out_path: Path) -> None:
    """复核用 overlay：绿框=模板，蓝框=文本锚定，橙框=位置先验。"""
    from annotate_live import annotate  # 复用中文标签绘制
    dets = []
    src_color = {"tmpl": (0, 255, 0), "ocr": (255, 128, 0), "prior": (0, 165, 255)}
    for (cid, cx, cy, bw, bh), p in zip(boxes, prov):
        h, w = img.shape[:2]
        x1, y1 = int((cx - bw / 2) * w), int((cy - bh / 2) * h)
        x2, y2 = int((cx + bw / 2) * w), int((cy + bh / 2) * h)
        src = p.rsplit("<-", 1)[-1]
        dets.append({"cid": cid, "name": names[cid], "conf": 0.0,
                     "xyxy": (x1, y1, x2, y2), "level": "",
                     "_src": src_color.get(src, (255, 255, 255))})
    vis = annotate(img, dets)
    for d in dets:  # annotate 用类 id 上色，这里再用来源色描一遍边框
        x1, y1, x2, y2 = d["xyxy"]
        cv2.rectangle(vis, (x1, y1), (x2, y2), d["_src"], 3)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", vis)[1].tofile(str(out_path))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=ROOT / "raw_imgs")
    ap.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    ap.add_argument("--manifest", type=Path, default=ROOT / "templates" / "manifest.yaml")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写任何文件")
    ap.add_argument("--force", action="store_true",
                    help="覆盖已入库帧的标注（默认跳过已存在的帧）")
    ap.add_argument("--allow-odd-size", action="store_true",
                    help="允许非 1920x1080 的帧入库（不推荐：ROI 会错位）")
    ap.add_argument("--write-empty", action="store_true",
                    help="0 框也入库并写空标注。默认跳过——0 框通常意味着预标注失败，"
                         "写成空标注等于教模型「这里没有目标」")
    ap.add_argument("--full-frame", action="store_true",
                    help="模板全帧搜，忽略 manifest 的 ROI。会大量误报（实测 preset_* "
                         "串位、958/1918 框越界），只在对某批帧确认 ROI 全错位时用")
    args = ap.parse_args()

    ds_yaml = args.dataset / "dataset.yaml"
    if not ds_yaml.exists():
        print(f"找不到 {ds_yaml}")
        return 1
    names, names_inv = _load_dataset_yaml(ds_yaml)
    print(f"dataset.yaml: {len(names)} 类（只读，不会重新生成）")

    registry = TemplateRegistry.load(args.manifest)
    specs = registry._t
    templates: dict[str, np.ndarray] = {}
    for tid, spec in specs.items():
        img = cv2.imread(str(spec.file))
        if img is not None:
            templates[tid] = img
    print(f"manifest: {len(templates)} 个模板可加载")

    # 收集待入库帧
    frames: list[tuple[str, Path]] = []
    for scene in SCENES:
        d = args.raw / scene
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.png")):
            frames.append((scene, p))
    if not frames:
        print(f"\n{args.raw} 下没有待入库的截图。把图按场景丢进子目录后再跑。")
        return 0
    print(f"待入库帧: {len(frames)}")

    ocr = _Ocr()
    images_dir = args.dataset / "images"
    labels_dir = args.dataset / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    new_train: list[str] = []
    new_val: list[str] = []
    per_scene: dict[str, dict] = {}
    skipped: list[str] = []
    no_box: list[str] = []
    rng = random.Random(SEED)
    rng.shuffle(frames)  # 先打散，保证 val 抽样不偏向某个场景

    # 内容级去重。文件名不同挡不住这件事：用户补图时把同一个画面存了两遍很常见
    # （2026-09-27 实测 raw_imgs/04_march_preset 有 7 帧与已入库的 manual3_formation_*
    # 逐字节相同）。孪生帧一个落 train 一个落 val，val 指标直接虚高；就算都在 train，
    # 同一份输入配两遍不一致的标注也是有害监督。`tools/dedupe_dataset.py` 只看
    # dataset/，管不到入库这一侧——这道闸必须开在入口。
    ingested_md5 = _index_images(images_dir)

    for i, (scene, src) in enumerate(frames):
        img = cv2.imread(str(src))
        if img is None:
            skipped.append(f"{src} (读不出)")
            continue
        h, w = img.shape[:2]
        if (w, h) != (NATIVE_W, NATIVE_H) and not args.allow_odd_size:
            skipped.append(f"{src} ({w}x{h}，非 {NATIVE_W}x{NATIVE_H}，ROI 会错位)")
            continue

        flat = f"{scene}__{src.name}"
        link = images_dir / flat
        label = labels_dir / Path(flat).with_suffix(".txt")

        # 与已入库帧逐字节相同 → 永不入库（--force 也不放行：孪生帧没有任何
        # 合法用途）。同名帧由下面的 link.exists() 报「已入库」，这里只管换名的。
        digest = _md5(src)
        twin = _twin_of(digest, ingested_md5, flat)
        if twin is not None:
            skipped.append(f"{src} (与已入库 {twin} 逐字节相同)")
            continue

        if link.exists() and not args.force:
            skipped.append(f"{src} (已入库，--force 可覆盖)")
            continue

        boxes, prov, scores = prelabel(img, scene, names_inv, templates, specs, ocr,
                                       use_roi=not args.full_frame)

        st = per_scene.setdefault(scene, {"frames": 0, "boxes": 0, "cls": {},
                                          "best": {}, "best_full": {}})
        st["frames"] += 1
        st["boxes"] += len(boxes)
        for k in ("best", "best_full"):
            for tid, score in scores[k].items():
                st[k][tid] = max(st[k].get(tid, 0.0), score)
        for (cid, *_rest), p in zip(boxes, prov):
            st["cls"].setdefault(names[cid], []).append(p.rsplit("<-", 1)[-1])

        if not boxes and not args.write_empty:
            # 0 框通常意味着预标注失败（几何错位/状态不符），不是「这帧没有目标」。
            # 仍渲染 overlay 供诊断，但**不入库、不写空标注**。
            _render(img, boxes, names, prov, ROOT / "logs" / "review" / flat)
            no_box.append(f"{src} (0 框，跳过；确认确为负样本再加 --write-empty)")
            if args.force and link.exists():
                # --force 重跑后这帧变成 0 框：旧标注是上一版逻辑的产物，留着就是脏数据
                # （典型：全帧搜时的 preset_* 串位框）。连硬链接一起撤掉，随后由
                # _prune_split 把它从 train/val 里摘干净。
                label.unlink(missing_ok=True)
                link.unlink(missing_ok=True)
            continue

        # 这帧确定要进库了才入册：让同一批里的第二份孪生帧也被上面那道闸拦下。
        # 放在 dry-run 分支之前，dry-run 的「入库 N 帧」才与实际写盘一致。
        ingested_md5.setdefault(digest, Path(flat).stem)

        if args.dry_run:
            _render(img, boxes, names, prov,
                    ROOT / "logs" / "review" / flat)
            continue

        # 先定 split 再落盘。中途崩溃时留下的是「指向缺失图的 split 行」——
        # `_prune_split` 会摘掉；反过来（先落盘后写 split）留下的是「有图却没有
        # split 行」的孤儿帧，没有任何工具会发现，那帧就静默地不参与训练
        # （2026-09-27 实测：一次崩溃漏掉 1 帧，直到逐帧核对才发现）。
        # 复用 auto_label 的 val 比例；新帧独立抽样，不动既有划分
        if rng.random() < VAL_RATIO:
            new_val.append(str(link.resolve()))
        else:
            new_train.append(str(link.resolve()))

        if not link.exists():
            try:
                os.link(src, link)   # 硬链接：零额外磁盘，同 auto_label_yolo 的做法
            except OSError:
                shutil.copy2(src, link)
        label.write_text("\n".join(
            f"{cid} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"
            for cid, cx, cy, bw, bh in boxes), encoding="utf-8")
        _render(img, boxes, names, prov, ROOT / "logs" / "review" / flat)

        if (i + 1) % 20 == 0:
            print(f"  [{i + 1}/{len(frames)}] ...")

    # --- 覆盖报告 ---
    print("\n=== 覆盖报告（预期类 vs 实得框）===")
    for scene in SCENES:
        st = per_scene.get(scene)
        if st is None:
            continue
        desc = SCENES[scene]["desc"]
        print(f"\n{scene}  ({desc})  {st['frames']} 帧 / {st['boxes']} 框")
        for cls in SCENES[scene]["classes"]:
            got = st["cls"].get(cls)
            if got:
                srcs = ",".join(sorted(set(got)))
                print(f"    {zh(cls):<16} {cls:<22} {len(got):>3} 框  [{srcs}]")
            else:
                # 0 框分几种：无模板（只能手标）、ROI 内分数低（模板与这版 UI 不符）、
                # ROI 内低但全帧高（**ROI 错位**，该补 ROI 或手补框）。
                # 不区分的话都只看到「0 框」——这正是先前 39 帧被静默跳过的原因。
                bs = st["best"].get(cls)
                bf = st["best_full"].get(cls)
                if bs is None:
                    hint = "无模板，需人工标"
                elif bf is not None and bf >= 0.9 and bf > bs + 0.3:
                    hint = f"ROI 内 {bs:.3f} 但全帧 {bf:.3f} → ROI 错位，需手补或改 ROI"
                elif bs >= 0.6:
                    hint = f"模板最高 {bs:.3f}，接近阈值→可能只是位置/状态不同"
                else:
                    hint = f"模板最高 {bs:.3f}，与这版 UI 不符"
                print(f"    {zh(cls):<16} {cls:<22}   0 框  <<< {hint}")
        extra = set(st["cls"]) - set(SCENES[scene]["classes"])
        for cls in sorted(extra):
            print(f"    {zh(cls):<16} {cls:<22} {len(st['cls'][cls]):>3} 框  [场景外]")

    if args.dry_run:
        print(f"\n[dry-run] 未写任何文件。复核 overlay -> logs/review/")
        _print_skips(skipped, no_box)
        return 0

    # --- 增量合并 train/val（读-合并-重写，绝不截断）---
    train_txt = args.dataset / "train.txt"
    val_txt = args.dataset / "val.txt"
    old_train, old_val = _read_list(train_txt), _read_list(val_txt)
    n_tr, train_lines = _merge_split(train_txt, new_train, taken=old_val)
    n_va, val_lines = _merge_split(val_txt, new_val, taken=old_train)
    train_lines, gone_tr = _prune_split(train_lines)
    val_lines, gone_va = _prune_split(val_lines)
    # 收尾对账：历史遗留的同帧跨 split 行（旧版没有 taken 拦截时写进去的）从 val 侧摘掉，
    # 保留 train 侧——先分好的划分不动，val 只留干净留出集。
    train_lower = {p.lower() for p in train_lines}
    before = len(val_lines)
    val_lines = [p for p in val_lines if p.lower() not in train_lower]
    overlap = before - len(val_lines)
    _write_list(train_txt, train_lines)
    _write_list(val_txt, val_lines)
    print(f"\ntrain.txt: {len(train_lines)} 行（新增 {n_tr}，摘掉失效 {gone_tr}）")
    print(f"val.txt:   {len(val_lines)} 行（新增 {n_va}，摘掉失效 {gone_va}，"
          f"摘掉与 train 重叠 {overlap}）")

    orphans = _orphans(images_dir, train_lines + val_lines)
    if orphans:
        print(f"\n!!! 有图却不在任何 split 里的孤儿帧 {len(orphans)} 个"
              f"（不参与训练，且不会报错）：")
        for name in orphans[:10]:
            print(f"      {name}")
        if len(orphans) > 10:
            print(f"      …… 另 {len(orphans) - 10} 个")

    # ultralytics 的标签扫描缓存：不删会导致新图漏读（训练时自动重建）
    cache = args.dataset / "labels.cache"
    if cache.exists():
        cache.unlink()
        print("已删 dataset/labels.cache（下次训练自动重建）")

    print(f"复核 overlay -> logs/review/")
    _print_skips(skipped, no_box)
    return 0


if __name__ == "__main__":
    sys.exit(main())
