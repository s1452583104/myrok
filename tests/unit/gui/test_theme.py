"""gui/theme.py：设计令牌 + 全局 QSS。

这一层是「全仓库色值唯一出处」的守门人，所以测试重点不是渲染效果，而是
**一致性约束**——令牌层级是否有序、QSS 占位符是否都被令牌填满、状态标签
五个语义是否齐备。渲染效果靠离屏探针自查（见 `_probe_ui_theme.py`）。
"""
import os
from string import Template

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QLineEdit, QPushButton

from rok_assistant.gui import theme


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------- 令牌层级
def test_spacing_tokens_are_strictly_increasing():
    """间距必须单调递增：一旦有并列值，用哪档就成了随意的，规范即失效。"""
    steps = [theme.SP_XS, theme.SP_SM, theme.SP_MD,
             theme.SP_LG, theme.SP_XL, theme.SP_2XL]
    assert steps == sorted(steps)
    assert len(set(steps)) == len(steps)


def test_spacing_tokens_are_multiples_of_four():
    """8px 栅格（4 的半格是允许的最小步进）——出现 6px、10px 就是漂移。"""
    for v in (theme.SP_XS, theme.SP_SM, theme.SP_MD,
              theme.SP_LG, theme.SP_XL, theme.SP_2XL):
        assert v % theme.SP_XS == 0


def test_radius_tokens_are_strictly_increasing():
    steps = [theme.RADIUS_SM, theme.RADIUS_MD,
             theme.RADIUS_CONTROL, theme.RADIUS_CARD]
    assert steps == sorted(steps)
    assert len(set(steps)) == len(steps)


def test_font_size_tokens_are_strictly_increasing():
    steps = [theme.FONT_SIZE_CAPTION, theme.FONT_SIZE_BODY,
             theme.FONT_SIZE_SUBTITLE, theme.FONT_SIZE_TITLE]
    assert steps == sorted(steps)
    assert len(set(steps)) == len(steps)


def test_card_radius_is_the_largest():
    """卡片/弹窗圆角必须大于按钮圆角——企业级里「容器比控件更圆」是硬约束，
    反过来（按钮比卡片还圆）会显得廉价。"""
    assert theme.RADIUS_CARD > theme.RADIUS_CONTROL > theme.RADIUS_MD


# ---------------------------------------------------------------- 色值
def test_all_colors_are_plain_hex():
    """QSS 对 rgba 浮点 alpha 的解析各版本不一致，令牌一律落成实色十六进制。"""
    names = [n for n in dir(theme) if n.isupper() and isinstance(getattr(theme, n), str)]
    color_names = [n for n in names if getattr(theme, n).startswith("#")]
    assert color_names, "一个色值令牌都没有？"
    for n in color_names:
        v = getattr(theme, n)
        assert len(v) == 7, f"{n}={v} 不是 #RRGGBB"


def test_primary_has_hover_and_active_variants():
    assert theme.PRIMARY != theme.PRIMARY_HOVER != theme.PRIMARY_ACTIVE


def test_status_colors_are_distinct():
    """成功/警告/错误三色必须互不相同，否则状态标签失去语义。"""
    trio = {theme.SUCCESS, theme.WARNING, theme.ERROR}
    assert len(trio) == 3
    assert theme.PRIMARY not in trio


# ---------------------------------------------------------------- 状态标签
@pytest.mark.parametrize("kind", ["success", "info", "warning", "error", "default"])
def test_every_tag_kind_is_complete(kind):
    """浅底 + 深字 + 同色点，三件套缺一不可。"""
    assert kind in theme.TAG_BG
    assert kind in theme.TAG_FG
    assert kind in theme.TAG_DOT
    assert theme.tag_style(kind)
    assert theme.dot_style(kind)


def test_tag_bg_fg_dot_have_identical_keys():
    assert set(theme.TAG_BG) == set(theme.TAG_FG) == set(theme.TAG_DOT)


def test_tag_style_contains_background_color_and_radius():
    style = theme.tag_style("success")
    assert f"background:{theme.TAG_BG['success']}" in style
    assert f"color:{theme.TAG_FG['success']}" in style
    assert f"border-radius:{theme.RADIUS_SM}px" in style
    assert f"font-size:{theme.FONT_SIZE_CAPTION}px" in style


def test_tag_style_unknown_kind_falls_back_to_default():
    """新状态名冒出来时界面不该空白——回落而不是抛 KeyError。"""
    assert theme.tag_style("brand-new-kind") == theme.tag_style("default")
    assert theme.dot_style("brand-new-kind") == theme.dot_style("default")


def test_dot_style_is_a_solid_square_source():
    """圆点是 6×6 的 QLabel，靠 border-radius 变圆；这里只断言给了底色。"""
    assert theme.TAG_DOT["error"] in theme.dot_style("error")


# ---------------------------------------------------------------- QSS 拼装
def test_qss_renders_without_leftover_placeholders():
    rendered = theme.QSS.substitute(theme._TOKENS)
    assert "$" not in rendered


def test_every_qss_placeholder_has_a_token():
    """`substitute` 会在缺令牌时抛 KeyError——但那是**运行时**才炸（开窗即崩）。
    这里提前把占位符集合与令牌集合对一遍，缺哪个直接报名字。"""
    used = set(Template(theme.QSS.template).get_identifiers())
    missing = used - set(theme._TOKENS)
    assert not missing, f"QSS 用了没有令牌的占位符：{sorted(missing)}"


def test_no_dead_tokens():
    """反向：令牌表里留了没人用的键，说明 QSS 改过而令牌没跟着收——迟早两处对不上。"""
    used = set(Template(theme.QSS.template).get_identifiers())
    unused = set(theme._TOKENS) - used
    assert not unused, f"令牌表里有 QSS 用不到的键：{sorted(unused)}"


def test_qss_declares_the_primary_button_selector():
    """主按钮靠动态属性选中；选择器名写错就退化成普通按钮，且不会报错。"""
    assert 'QPushButton[primary="true"]' in theme.QSS.template


def test_qss_has_no_box_shadow():
    """QSS 根本不支持 box-shadow，写了也是静默失效——出现即是误解。"""
    assert "box-shadow" not in theme.QSS.template


# ---------------------------------------------------------------- 按钮标记
def test_make_primary_sets_property(qapp):
    btn = QPushButton("开始运行")
    theme.make_primary(btn)
    assert btn.property("primary") is True


def test_make_dashed_and_danger_set_properties(qapp):
    a, b = QPushButton("添加"), QPushButton("删除")
    theme.make_dashed(a)
    theme.make_danger(b)
    assert a.property("dashed") is True
    assert b.property("danger") is True


def test_marking_is_idempotent(qapp):
    """重复标记不该翻回 False（重新建卡时会再标一次）。"""
    btn = QPushButton("开始运行")
    theme.make_primary(btn)
    theme.make_primary(btn)
    assert btn.property("primary") is True


def test_make_mono_pins_the_family_via_object_name(qapp):
    """光 `setFont()` 盖不过全局 QSS 的 `QWidget { font-family }`（样式表的
    字体属性优先于控件字体）——本次重构真踩到：机器码从等宽变回了雅黑。
    `make_mono` 靠 objectName + `#monoText` 这个更具体的选择器把族钉回来。
    """
    edit = QLineEdit("ABCD-EFGH-IJKL")
    theme.make_mono(edit)
    assert edit.objectName() == "monoText"


def test_mono_text_actually_renders_monospace(qapp):
    """上一条只断言打了标记；这条走完整链路（装主题 → 建控件 → 读回字体），
    证明 QSS 真的生效了——选择器写错时它是唯一会红的。"""
    theme.apply_theme(qapp)
    edit = QLineEdit("ABCD-EFGH-IJKL")
    theme.make_mono(edit)
    assert edit.font().families()[0] == theme.MONO_FAMILIES[0]
    assert edit.font().pointSize() == 11


def test_mono_text_point_size_is_overridable(qapp):
    """字号由 setFont 给（QSS 不设 font-size），调用方要能改。"""
    theme.apply_theme(qapp)
    edit = QLineEdit()
    theme.make_mono(edit, 10)
    assert edit.font().pointSize() == 10


# ---------------------------------------------------------------- 应用
def test_apply_theme_installs_global_qss(qapp):
    theme.apply_theme(qapp)
    qss = qapp.styleSheet()
    assert "QPushButton[primary" in qss
    assert "$" not in qss


def test_apply_theme_switches_to_fusion(qapp):
    """必须先切 Fusion：Windows 默认的 windowsvista 样式会忽略
    QComboBox / QSpinBox 的大量 QSS 属性，不切则表单永远刷不齐。

    装了样式表之后 `QApplication.style()` 返回的是 QStyleSheetStyle 代理
    （`objectName` 为空、拿不到 `baseStyle()`），基础样式被它挡在后面——
    所以得先把样式表清掉才读得到，读完再装回去（qapp 是整个测试会话共用的）。
    """
    theme.apply_theme(qapp)
    qss = qapp.styleSheet()
    try:
        qapp.setStyleSheet("")
        assert qapp.style().metaObject().className() == "QFusionStyle"
    finally:
        qapp.setStyleSheet(qss)


def test_apply_theme_sets_body_font_size(qapp):
    theme.apply_theme(qapp)
    assert qapp.font().pixelSize() == theme.FONT_SIZE_BODY
