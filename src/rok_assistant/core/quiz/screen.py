"""屏幕解析：把 OCR 文本块还原成「题干 + A/B/C/D 四个选项」。

分辨率无关：全部判据用相对位置与块间关系，不出现任何绝对坐标。
素材实测有 2664×1200 与 1280×576 两种尺寸，都不是 1080p。

比参考实现严的地方（都是素材里暴露出来的坑）：
  * 分列轴 = **画面中线**，跨轴块整块丢掉（提示语/复活 toast 都横跨轴）
  * 丢「只有 1 个成员的行」（倒计时、剩余人数都是孤立行）
  * 必须恰好 2 行 × 每行 1 左 1 右，否则返回 None（宁可不点，不要点错）
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from .models import LETTERS, ScreenQuestion, TextBlock

# 答题界面的标题词（活动页 / 复试页 / 习题演练页）
TITLE_KEYWORDS = ("国士无双", "国王无双", "习题演练", "知识问答", "复试", "初试")

# 按钮/界面文字，永远不是选项
UI_NOISE = frozenset({"放弃", "求助", "确定", "开始", "继续", "退出", "返回",
                      "关闭", "分享"})

# 界面上的动态文字（倒计时、人数、奖励……），一律不作为选项
NOISE_PATTERNS = ("剩余时间", "答题时间", "倒计时", "通过后可获", "暂入", "已答",
                  "积分", "排名", "宝石", "关卡", "观看", "复活", "求助")

# 活动页的入口候选，按优先级排列：真按钮 > 加大字号的卡片标题 > 地图上的活动图标
ENTRY_LABELS = ("进入", "习题演练", "活动")

_Q_RE = re.compile(r"^Q\s*(\d+)$", re.I)
_OPT_PREFIX_RE = re.compile(r"^\s*([ABCDabcd])[\.．、:：\s\)）]*\s*(.+)$")
_CJK_RE = re.compile(r"[一-鿿]")
# 纯数字/计数/时间码（`00:16 /01:06` 也算）：这类块不可能是选项
_NUMERIC_RE = re.compile(r"^[\d\s,，\.%\+\-/:：]+$")


def detect_quiz(blocks: Sequence[TextBlock]) -> bool:
    """当前屏幕是不是答题界面。

    活动页也会命中（标题里有「国士无双」）——所以**判定入口是否已进入
    答题界面要用 parse_question()，不是这个函数**。
    """
    texts = [text.strip() for _box, text, _conf in blocks]
    if any(k in " ".join(texts) for k in TITLE_KEYWORDS):
        return True
    return any(_Q_RE.match(t) for t in texts)


def _find_q_marker(blocks: Sequence[TextBlock]) -> int | None:
    for i, (_box, text, _conf) in enumerate(blocks):
        if _Q_RE.match(text.strip()):
            return i
    return None


def _pick_question_text(blocks: Sequence[TextBlock]) -> tuple[str, int]:
    """挑出题干与其底边 y（`q_bottom`）。挑不出返回 ("", 0)。"""
    marker_idx = _find_q_marker(blocks)
    if marker_idx is not None:
        mbox = blocks[marker_idx][0]
        line_h = max(mbox.y2 - mbox.y1, 1)
        first: tuple | None = None
        for i, (box, text, _conf) in enumerate(blocks):
            t = text.strip()
            if i == marker_idx or _OPT_PREFIX_RE.match(t):
                continue
            if not (box.y1 < mbox.y2 and box.y2 > mbox.y1):    # 与题号同一行
                continue
            if box.x1 < mbox.x2:                               # 必须在题号右侧
                continue
            if first is None or len(t) > len(first[1]):
                first = (box, t)
        if first is not None:
            fbox, ftext = first
            parts, bottom = [ftext], fbox.y2
            x_right = fbox.x2
            for (box, text, _conf) in blocks:
                t = text.strip()
                if _OPT_PREFIX_RE.match(t):
                    continue
                if not t or t in UI_NOISE or any(p in t for p in NOISE_PATTERNS):
                    continue
                # 续行：上一行底边往下 0.5~1.5 个行高
                if not (bottom - line_h * 0.5 <= box.y1 <= bottom + line_h * 1.5):
                    continue
                if box.x1 > x_right + line_h * 3:
                    continue
                parts.append(t)
                bottom = max(bottom, box.y2)
                x_right = max(x_right, box.x2)
            return "".join(parts), int(bottom)

    # 退化：含问号的最长块
    cands = [(box, text.strip()) for box, text, _conf in blocks
             if ("？" in text or "?" in text)
             and not _OPT_PREFIX_RE.match(text.strip())
             and text.strip() not in UI_NOISE
             and not any(p in text for p in NOISE_PATTERNS)]
    if not cands:
        return "", 0
    box, text = max(cands, key=lambda c: len(c[1]))
    return text, int(box.y2)


def _looks_like_option(text: str) -> bool:
    if _NUMERIC_RE.fullmatch(text):
        return False
    if _CJK_RE.search(text):
        return True
    return len(text) >= 3


def _is_option_candidate(box, text: str, q_bottom: int, midline: float) -> bool:
    t = text.strip()
    if not t or t in UI_NOISE:
        return False
    if any(p in t for p in NOISE_PATTERNS):
        return False
    if _Q_RE.match(t):
        return False
    if re.fullmatch(r"[ABCDabcd]", t):        # 孤立字母块（A/B/C/D 标记）
        return False
    if q_bottom and box.y1 < q_bottom:        # 题干上方（标题栏、HUD）
        return False
    if box.x1 < midline <= box.x2:            # 跨轴：提示语、toast、HUD 长行
        return False
    return _looks_like_option(t)


def _parse_by_letter(blocks: Sequence[TextBlock],
                     q_bottom: int) -> dict[str, tuple[str, str]]:
    """带 A/B/C/D 前缀的块：命中时以字母为准，几何只用来补齐缺失字母。"""
    out: dict[str, tuple[str, str]] = {}
    for box, text, _conf in blocks:
        m = _OPT_PREFIX_RE.match(text.strip())
        if m is None:
            continue
        if q_bottom and box.y1 < q_bottom:
            continue
        letter = m.group(1).upper()
        if letter in LETTERS and letter not in out:
            out[letter] = (m.group(2).strip(), box)
    return out


def _overlap(a, b) -> bool:
    return a.x1 < b.x2 and b.x1 < a.x2 and a.y1 < b.y2 and b.y1 < a.y2


def _parse_by_geometry(blocks: Sequence[TextBlock], q_bottom: int,
                       frame_width: int) -> dict[str, tuple[str, object]]:
    """按 2×2 排布指派字母。不满足「恰好 2 行、每行 1 左 1 右」就返回 {}。"""
    midline = frame_width / 2.0
    pool = [(box, text.strip()) for box, text, _conf in blocks
            if _is_option_candidate(box, text, q_bottom, midline)]
    if len(pool) < 4:
        return {}

    heights = sorted(b.y2 - b.y1 for b, _t in pool)
    tol = max(1.0, heights[len(heights) // 2] * 0.6)

    rows: list[list[tuple]] = []
    for item in sorted(pool, key=lambda p: p[0].y1):
        for row in rows:
            if abs(item[0].y1 - row[0][0].y1) <= tol:
                row.append(item)
                break
        else:
            rows.append([item])

    # 孤立行是 HUD（倒计时 / 剩余人数 / 弹幕计数），不是选项
    rows = [r for r in rows if len(r) >= 2]
    if len(rows) != 2:
        return {}

    out: dict[str, tuple[str, object]] = {}
    for r_idx, row in enumerate(rows):
        left = [p for p in row if p[0].x2 <= midline]
        right = [p for p in row if p[0].x1 >= midline]
        if len(left) != 1 or len(right) != 1:
            return {}
        out[LETTERS[r_idx * 2]] = (left[0][1], left[0][0])
        out[LETTERS[r_idx * 2 + 1]] = (right[0][1], right[0][0])

    boxes = [out[k][1] for k in LETTERS]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _overlap(boxes[i], boxes[j]):
                return {}
    return out


def parse_question(blocks: Sequence[TextBlock],
                   frame_width: int) -> ScreenQuestion | None:
    """还原题干与四个选项；拿不到**恰好 4 个**选项就返回 None。

    `frame_width` 只用来算分列轴（`frame_width / 2`）——**不要**用题干中心，
    短题干的中心会落进左列选项的 x 区间，把真选项判成跨轴。
    """
    text, q_bottom = _pick_question_text(blocks)
    if not text:
        return None

    options = _parse_by_letter(blocks, q_bottom)
    if len(options) < 4:
        geo = _parse_by_geometry(blocks, q_bottom, frame_width)
        if len(options) >= 2:
            for letter in LETTERS:
                if letter not in options and letter in geo:
                    options[letter] = geo[letter]
        elif len(geo) == 4:
            options = geo
    if len(options) != 4:
        return None
    return ScreenQuestion(text=text,
                          options={letter: options[letter] for letter in LETTERS})


def _entry_candidates(blocks: Sequence[TextBlock], label: str) -> list:
    """同一入口标签的候选块。文本**恰好等于**标签的优先——`每日习题演练
    来获取奖励` 这类说明文字不是入口，哪怕 OCR 置信度更高；没有精确块时
    才退回包含匹配（地图图标常写成 `限时活动`）。"""
    hits = [(box, text.strip(), conf) for box, text, conf in blocks
            if label in text.strip()]
    exact = [h for h in hits if h[1] == label]
    return exact or hits


def find_quiz_entry(blocks: Sequence[TextBlock]) -> tuple[int, int] | None:
    """在活动页上找「进入答题」的点击点（返回像素中心）。

    优先级：`进入` 按钮 > `习题演练` 卡片标题 > 地图上的 `活动` 图标。
    同一级里取置信度最高的块（不是最大号的块：右栏 40px 的「习题演练」
    栏目头比 37px 的可点卡片行更高，却点不进去）；没有任何候选就返回
    None（调用方据此写 `quiz_entry_missing`，**不要**乱点）。
    """
    # 已经看到题号（Q1/Q2…）说明人在答题界面里：顶部的「习题演练」是
    # 标题不是入口，点它没有意义。
    if _find_q_marker(blocks) is not None:
        return None
    for label in ENTRY_LABELS:
        cands = _entry_candidates(blocks, label)
        if not cands:
            continue
        return max(cands, key=lambda c: c[2])[0].center()
    return None


# 入口倒计时：「距开始还有 01:13:43」。没到开始时间，「进入」按钮置灰，
# 点了不生效（2026-10-24 用户截图 + 录屏实证）。兼容「距离开始还有」变体。
_COUNTDOWN_RE = re.compile(r"距[离开]?开?始还有")


def entry_countdown_active(blocks: Sequence[TextBlock]) -> bool:
    """当前活动页的入口是否还在「距开始还有」倒计时中。

    倒计时期间进入按钮置灰，调用方（quiz_sm）据此**原地等待**，而不是
    反复点一个点不动的按钮。只认**开始**倒计时：「距结束还有」说明活动
    已开、即将结束，该进就进，不能被它挡住。

    文案变体（`距离开始还有`）与 OCR 把标签和时间并成一块
    （`距开始还有01:13:43`）都能认；`开始时间：13:00` 这类常态文案
    不含「还有」，不会误判。
    """
    return any(_COUNTDOWN_RE.search(text.strip()) for _box, text, _conf in blocks)


# 考试类型（用户 2026-10-24 补充的活动规则）：初试周六、终试周日，都是
# 固定时间入场（13:00/19:00 两场）、单题限时，初试 10 题、终试 20 题；
# 周一到周五的日常答题任意时间可答、无单题时限、题量不固定。
EXAM_PRELIM = "prelim"
EXAM_FINAL = "final"
EXAM_LABELS = {EXAM_PRELIM: "初试", EXAM_FINAL: "终试"}
# 考试的单轮题量上限（真实题量）；日常答题用 quiz.max_questions_per_round
EXAM_QUESTION_LIMITS = {EXAM_PRELIM: 10, EXAM_FINAL: 20}
_EXAM_TYPE_PATTERNS = ((EXAM_PRELIM, re.compile(r"初试")),
                       (EXAM_FINAL, re.compile(r"终试")))


def detect_exam_type(blocks: Sequence[TextBlock]) -> str | None:
    """题目帧上识别当前是初试还是终试；认不出返回 None（日常答题）。

    **只在题目帧调用**：入场弹窗（「本场初试开始后将无法再……终试」）
    和活动主页（初试历史卡 + 终试明天卡并存）都会同时出现两个考试名，
    这种情况返回 None——调用方保持原状，避免把题量上限设错。
    「复试」等旧写法不匹配（不是初试/终试）。
    """
    hits = [exam for exam, rx in _EXAM_TYPE_PATTERNS
            if any(rx.search(text.strip()) for _box, text, _conf in blocks)]
    return hits[0] if len(hits) == 1 else None
