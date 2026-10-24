"""答题屏幕解析：题干 + 2×2 选项。

所有块数据来自真实帧的 OCR 输出（两种分辨率：2664×1200 静止帧、
1280×576 视频帧），坐标未改。合成的「干净数据」测不出跨轴提示语、
孤立倒计时行这些真坑。
"""
from rok_assistant.core.quiz.models import LETTERS
from rok_assistant.core.quiz.screen import (
    detect_exam_type, detect_quiz, entry_countdown_active, find_quiz_entry,
    parse_question,
)
from rok_assistant.core.recognizer import BBox


def _blocks(*rows):
    """(x1, y1, x2, y2, text, conf) → detect_text() 的返回形状。"""
    return [(BBox(r[0], r[1], r[2], r[3]), r[4], r[5]) for r in rows]


# 活动页（2664×1200）：真实帧 38 块，这里保留有判据意义的 9 块，坐标原样
ACTIVITY = _blocks(
    (1160, 24, 1507, 114, "国士无双", 0.78),
    (2516, 77, 2566, 111, "25", 0.67),
    (2522, 146, 2577, 179, "日程", 0.66),
    (1547, 388, 1688, 428, "习题演练", 0.73),
    (399, 431, 530, 468, "习题演练", 0.76),
    (687, 431, 817, 468, "习题演练", 0.74),
    (975, 431, 1106, 468, "习题演练", 0.71),
    (1263, 431, 1393, 468, "习题演练", 0.75),
    (1585, 878, 1648, 915, "进入", 0.67),
)

# 国士无双答题页·初试倒计时未结束（1920×1080 真实帧，2026-10-24 用户截图，
# RapidOcrEngine 原样输出）：「距开始还有」与时间是分开两块，进入按钮置灰。
COUNTDOWN = _blocks(
    (806, 26, 1117, 103, "国士无双", 0.76),
    (1445, 350, 1508, 384, "初试", 0.66),
    (1410, 507, 1525, 537, "开始时间：", 0.75),
    (1441, 537, 1510, 561, "13:00", 0.83),
    (1440, 563, 1511, 591, "19:00", 0.78),
    (1411, 742, 1537, 772, "距开始还有", 0.75),
    (1420, 771, 1532, 798, "01:13:43", 0.84),
    (1443, 849, 1499, 882, "进入", 0.66),
)

# Q1（2664×1200）：注意题干很短，中心 x≈1014 落在左列选项的 x 区间里
Q1 = _blocks(
    (2183, 30, 2273, 60, "剩余人数", 0.69),
    (1092, 60, 1485, 116, "国士无双-复试", 0.75),
    (2144, 60, 2273, 101, "10,057", 0.70),
    (2143, 112, 2270, 135, "通过后可获得", 0.84),
    (2202, 136, 2276, 176, "150", 0.75),
    (752, 393, 809, 436, "Q1", 0.63),
    (832, 394, 1197, 431, "统帅贝利撒留的昵称是？", 0.89),
    (1554, 594, 1700, 634, "战火双刃", 0.79),
    (823, 597, 1032, 631, "最后的罗马人", 0.81),
    (821, 756, 965, 793, "天选之豹", 0.74),
    (1557, 758, 1767, 791, "不的复兴者", 0.81),
    (1357, 916, 1608, 948, "答题剩余时间：9s", 0.82),
    (2245, 1151, 2316, 1192, "放弃", 0.67),
)

# Q2（2664×1200）：选项里带数字，归一化时不许把数字丢掉
Q2 = _blocks(
    (1092, 60, 1484, 116, "国士无双-复试", 0.75),
    (749, 389, 813, 438, "Q2", 0.66),
    (834, 397, 1686, 429, "联盟领土界面中，领土资源最多能储存多长时间的产量？", 0.90),
    (818, 595, 936, 633, "24小时", 0.79),
    (1555, 595, 1672, 633, "36小时", 0.74),
    (817, 754, 937, 794, "12小时", 0.80),
    (1551, 754, 1671, 795, "18小时", 0.80),
    (1348, 914, 1616, 948, "答题剩余时间：15s", 0.86),
    (2245, 1151, 2316, 1192, "放弃", 0.67),
)

# 视频帧（1280×576，10.9s）：提示语横跨分列轴，`求助`/`放弃` 是按钮
FRAME_358 = _blocks(
    (564, 27, 676, 59, "习题演练", 0.76),
    (362, 149, 391, 171, "Q2", 0.66),
    (402, 152, 813, 167, "2022年北京冬奥会的吉祥物是以什么动物为原型设计的？", 0.91),
    (380, 254, 433, 275, "考拉", 0.60),
    (745, 254, 786, 275, "狮子", 0.57),
    (392, 332, 431, 351, "大象", 0.54),
    (747, 332, 802, 351, "大熊猫", 0.71),
    (377, 410, 819, 429, "您一共拥有3次求助的机会，集合盟友的智慧，让他们助你渡过难关！", 0.94),
    (925, 431, 975, 458, "求助", 0.57),
    (1204, 545, 1245, 568, "放弃", 0.64),
)

# 视频帧（1280×576，57.5s）：复活 toast 横跨轴，且只 OCR 出 3 个选项
FRAME_1812 = _blocks(
    (525, 28, 715, 57, "国士无双-复试", 0.81),
    (362, 188, 391, 210, "Q3", 0.66),
    (401, 189, 778, 207, "哥伦布的冒险航海是由欧洲哪个国家的国王赞助的？", 0.90),
    (540, 269, 729, 290, "已消耗复活券成功复活！", 0.84),
    (394, 284, 449, 306, "葡萄牙", 0.68),
    (747, 284, 802, 306, "西班牙", 0.75),
    (394, 361, 449, 383, "意大利", 0.72),
    (1078, 553, 1114, 573, "放弃", 0.66),
)


def test_detect_quiz_on_activity_page_uses_the_title():
    assert detect_quiz(ACTIVITY) is True


def test_detect_quiz_on_question_frame():
    assert detect_quiz(Q1) is True
    assert detect_quiz(FRAME_358) is True


def test_detect_quiz_false_without_title_or_question_number():
    assert detect_quiz(_blocks((10, 10, 100, 40, "设置", 0.9))) is False


def test_activity_page_has_no_question():
    """活动页没有题干、没有 2×2 选项：解析必须返回 None，绝不能把日期
    或「习题演练」当成选项去点。"""
    assert parse_question(ACTIVITY, frame_width=2664) is None


def test_parse_q1_still_assigns_all_four_letters():
    """短题干的中心（x≈1014）落在左列选项的 x 区间里——分列轴必须用
    **画面中线**（1332），不能用题干中心，否则「最后的罗马人」会被判成
    跨轴块丢掉，9 份素材里 4 份会因此解析失败。"""
    q = parse_question(Q1, frame_width=2664)
    assert q is not None
    assert q.text == "统帅贝利撒留的昵称是？"
    assert q.option_texts() == {
        "A": "最后的罗马人", "B": "战火双刃",
        "C": "天选之豹", "D": "不的复兴者",
    }
    assert letters_in_order(q) == list(LETTERS)


def letters_in_order(q):
    """按行读回字母顺序，钉住「上行左 A、上行右 B、下行左 C、下行右 D」。"""
    return [k for k, _v in q.options.items()]


def test_parse_q2_keeps_numbers():
    q = parse_question(Q2, frame_width=2664)
    assert q is not None
    assert q.option_texts() == {"A": "24小时", "B": "36小时",
                                "C": "12小时", "D": "18小时"}


def test_timer_block_is_dropped_as_a_singleton_row():
    """倒计时 `答题剩余时间：15s` 从轴右侧开始（1348 > 1332），**不是**靠
    跨轴规则扔掉的——它靠「只有 1 个成员的行」被丢。两条规则缺一不可。"""
    q = parse_question(Q2, frame_width=2664)
    assert q is not None
    assert all("答题剩余时间" not in t for t in q.option_texts().values())


def test_parse_1280_video_frame():
    q = parse_question(FRAME_358, frame_width=1280)
    assert q is not None
    assert q.text == "2022年北京冬奥会的吉祥物是以什么动物为原型设计的？"
    assert q.option_texts() == {"A": "考拉", "B": "狮子",
                                "C": "大象", "D": "大熊猫"}


def test_cross_axis_tip_never_becomes_an_option():
    """`您一共拥有3次求助的机会…` 横跨中线（377–819），必须整块丢掉。"""
    q = parse_question(FRAME_358, frame_width=1280)
    assert q is not None
    joined = "".join(q.option_texts().values())
    assert "求助" not in joined and "盟友" not in joined


def test_three_options_is_a_parse_failure_not_a_guess():
    """57.5s 那帧只读出 3 个选项（印度漏检）：宁可不点，也不要点错。"""
    assert parse_question(FRAME_1812, frame_width=1280) is None


def test_letter_prefixes_win_over_geometry():
    blocks = _blocks(
        (100, 100, 140, 130, "Q1", 0.9),
        (150, 100, 600, 130, "测试题干？", 0.9),
        (120, 300, 400, 330, "A. 甲", 0.9),
        (700, 300, 900, 330, "B. 乙", 0.9),
        (120, 400, 400, 430, "C. 丙", 0.9),
        (700, 400, 900, 430, "D. 丁", 0.9),
    )
    q = parse_question(blocks, frame_width=1000)
    assert q is not None
    assert q.option_texts() == {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}


def test_find_quiz_entry_prefers_the_enter_button():
    """活动页真正的按钮是「进入」，不是「习题演练」标题（后者加大字号，
    点它不一定进得去）。中心 = ((1585+1648)//2, (878+915)//2)。"""
    assert find_quiz_entry(ACTIVITY) == (1616, 896)


def test_find_quiz_entry_falls_back_to_the_most_confident_practice_card():
    """没有「进入」时，`习题演练` 这一级取**置信度**最高的块：
    可点卡片行 (399,431,530,468) conf 0.76，高于栏目头 (1547,388,1688,428)
    的 0.73。按高度取会点到栏目头（2026-10-24 评审发现）。"""
    blocks = [b for b in ACTIVITY if b[1] != "进入"]
    assert find_quiz_entry(blocks) == (464, 449)


def test_find_quiz_entry_practice_tier_ignores_longer_text_blocks():
    """`每日习题演练来获取奖励` 这类说明文字不是入口，哪怕置信度更高；
    入口块文本应当就是标签本身。"""
    blocks = _blocks(
        (1547, 388, 1688, 428, "习题演练", 0.70),                 # 栏目头
        (399, 431, 530, 468, "习题演练", 0.76),                   # 可点卡片行
        (1500, 560, 1800, 600, "每日习题演练来获取奖励", 0.95),    # 无关说明块
    )
    assert find_quiz_entry(blocks) == (464, 449)


def test_find_quiz_entry_falls_back_to_the_activity_icon():
    """进入/习题演练都不在时，最后回退到地图上的「活动」图标。"""
    blocks = _blocks(
        (100, 100, 180, 140, "限时活动", 0.62),
        (500, 300, 600, 340, "日程", 0.90),
    )
    assert find_quiz_entry(blocks) == (140, 120)


def test_find_quiz_entry_returns_none_on_the_quiz_screen():
    assert find_quiz_entry(Q1) is None
    assert find_quiz_entry(FRAME_358) is None


def test_entry_countdown_active_on_the_real_countdown_frame():
    """倒计时未结束：「距开始还有」在，进入按钮置灰，点了也进不去。"""
    assert entry_countdown_active(COUNTDOWN) is True


def test_entry_countdown_inactive_on_the_open_activity_page():
    """没有倒计时文案的活动页：入口可点，不能被误挡。"""
    assert entry_countdown_active(ACTIVITY) is False


def test_entry_countdown_ignores_start_time_labels():
    """「开始时间：13:00」是活动页常态文案，不是倒计时，不能误挡。"""
    blocks = [b for b in COUNTDOWN if b[1] not in ("距开始还有", "01:13:43")]
    assert entry_countdown_active(blocks) is False


def test_entry_countdown_ignores_the_end_countdown():
    """「距结束还有」= 活动已开、即将结束：该进就进。"""
    blocks = _blocks(
        (1411, 742, 1537, 772, "距结束还有", 0.75),
        (1420, 771, 1532, 798, "00:42:18", 0.84),
        (1443, 849, 1499, 882, "进入", 0.66),
    )
    assert entry_countdown_active(blocks) is False


def test_entry_countdown_matches_variant_and_merged_wordings():
    """「距离开始还有」变体、以及标签和时间被 OCR 并成一块，都要认。"""
    assert entry_countdown_active(_blocks(
        (1411, 742, 1537, 772, "距离开始还有", 0.75),
        (1443, 849, 1499, 882, "进入", 0.66),
    )) is True
    assert entry_countdown_active(_blocks(
        (1411, 742, 1537, 798, "距开始还有01:13:43", 0.75),
        (1443, 849, 1499, 882, "进入", 0.66),
    )) is True


# ---- 考试类型识别（用户 2026-10-24 补充的活动规则） ----
#
# 国士无双分三种场次：初试（周六，10 题）、终试（周日，20 题）都是固定
# 时间入场、单题限时；周一到周五的日常答题任意时间可答、无单题时限。
# 状态机按识别到的类型决定单轮题量上限和补点预算。
#
# **检测点只在题目帧**：入场弹窗（「本场初试开始后将无法再……终试」）
# 和活动主页（初试历史卡 + 终试明天卡并存）都会同时出现两个考试名，
# 那种画面必须返回 None，由调用方保持原状。

def test_detect_exam_type_prelim_on_a_question_frame():
    """初试题目帧：头部考试名可见（1920×1080 真实帧坐标）。"""
    blocks = Q1 + _blocks((865, 49, 979, 110, "初试", 0.57))
    assert detect_exam_type(blocks) == "prelim"


def test_detect_exam_type_final_on_a_question_frame():
    blocks = Q1 + _blocks((865, 49, 979, 110, "终试", 0.57))
    assert detect_exam_type(blocks) == "final"


def test_detect_exam_type_none_for_daily_practice():
    """日常答题/习题演练的题目帧没有考试名：返回 None，用配置兜底。"""
    assert detect_exam_type(Q1) is None
    assert detect_exam_type(FRAME_358) is None


def test_detect_exam_type_none_when_both_names_coexist():
    """弹窗/活动主页两个考试名并存：不猜，返回 None。"""
    both = Q1 + _blocks((865, 49, 979, 110, "初试", 0.57),
                        (900, 300, 1014, 360, "终试", 0.60))
    assert detect_exam_type(both) is None


def test_detect_exam_type_survives_garbled_ocr():
    """OCR 把标题和考试名粘成一块（实机失败弹窗的「国初试无双」）也要认。"""
    blocks = _blocks((865, 49, 1050, 110, "国初试无双", 0.57))
    assert detect_exam_type(blocks) == "prelim"
