"""企业级视觉主题：设计令牌 + 全局 QSS。

令牌取值对标 Ant Design 5 / 华为云控制台（见
`.claude/skills/enterprise-ui-optimizer/references/design-tokens.md`）。

**所有界面色值、间距、字号只从这里取**——控件里禁止写死色值。重构前的教训：
全仓库 5 处零散 `setStyleSheet` 各自跑偏（`#500` 暗红 / `#c0392b` 深红 / 裸 `red`），
根因就是没有单一出处。

两条 Qt 落地注意：

- **阴影令牌在 Qt QSS 里没有对应属性**（QSS 不支持 `box-shadow`）。规范本身也要求
  「列表页、表单页优先用 1px 分割线分区，不加阴影」，故本主题一律用描边 + 留白，
  不引入 `QGraphicsDropShadowEffect`。
- **必须先切 Fusion**：Windows 默认的 `windowsvista` 样式会忽略 QComboBox / QSpinBox /
  QTableWidget 的大量 QSS 属性，不切样式表刷不齐。

QSS 用 `string.Template` 拼装（`$TOKEN` 占位）而不是 f-string——CSS 里满是 `{}`，
f-string 需要逐个转义成 `{{}}`，改一行 CSS 就得数括号。
"""
from __future__ import annotations

from string import Template

from PyQt6.QtGui import QFont

# ---------------------------------------------------------------- 间距（8px 基准）
SP_XS = 4
SP_SM = 8
SP_MD = 12
SP_LG = 16
SP_XL = 24
SP_2XL = 32

# ---------------------------------------------------------------- 圆角
RADIUS_SM = 2          # 标签、徽标
RADIUS_MD = 4          # 输入框、下拉、表格内层
RADIUS_CONTROL = 6     # 按钮
RADIUS_CARD = 8        # 卡片、弹窗、面板

# ---------------------------------------------------------------- 字号
FONT_SIZE_CAPTION = 12
FONT_SIZE_BODY = 14
FONT_SIZE_SUBTITLE = 16
FONT_SIZE_TITLE = 20

FONT_FAMILIES = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")
MONO_FAMILIES = ("Consolas", "Cascadia Mono", "Courier New")

# ---------------------------------------------------------------- 中性灰阶
# 令牌原文是 rgba(0,0,0,0.88) 这类半透明黑；这里落成**白底上的实色等价值**，
# 免得依赖 Qt QSS 对 rgba 浮点 alpha 的解析差异（不同版本行为不一致）。
TEXT_PRIMARY = "#1F1F1F"       # rgba(0,0,0,0.88)
TEXT_SECONDARY = "#595959"     # rgba(0,0,0,0.65)
TEXT_TERTIARY = "#8C8C8C"      # rgba(0,0,0,0.45)
TEXT_DISABLED = "#BFBFBF"      # rgba(0,0,0,0.25)
BORDER_BASE = "#D9D9D9"        # 输入框边框、强分割
BORDER_SPLIT = "#F0F0F0"       # 弱分割线、卡片边框
FILL_BASE = "#F5F5F5"          # 禁用态底、选中底
BG_CONTAINER = "#FFFFFF"       # 卡片、弹窗、面板
BG_LAYOUT = "#F0F2F5"          # 页面整体背景
BG_HEADER = "#FAFAFA"          # 表头、区块标题底

# ---------------------------------------------------------------- 品牌与功能色
PRIMARY = "#1677FF"
PRIMARY_HOVER = "#4096FF"
PRIMARY_ACTIVE = "#0958D9"
SUCCESS = "#52C41A"
WARNING = "#FAAD14"
ERROR = "#FF4D4F"
INFO = PRIMARY

# 选中态浅底（状态标签 / 表格行选中 / 树选中共用）
SELECT_BG = "#E6F4FF"

# ---------------------------------------------------------------- 状态标签
# 统一「浅底 + 深字 + 同色点」，圆角 2px、字号 12px（design-tokens §9）。
TAG_BG = {
    "success": "#F6FFED",
    "info": "#E6F4FF",
    "warning": "#FFFBE6",
    "error": "#FFF1F0",
    "default": FILL_BASE,
}
TAG_FG = {
    "success": "#389E0D",
    "info": "#0958D9",
    "warning": "#D48806",
    "error": "#CF1322",
    "default": TEXT_SECONDARY,
}
# 圆点用饱和度更高的功能色，与浅底形成对比（同色系、深一档）
TAG_DOT = {
    "success": SUCCESS,
    "info": PRIMARY,
    "warning": WARNING,
    "error": ERROR,
    "default": TEXT_DISABLED,
}

_TAG_TEMPLATE = Template(
    "background:$bg;color:$fg;border-radius:${radius}px;"
    "padding:1px ${pad_x}px;font-size:${font}px;"
)

_TAG_STYLES = {
    kind: _TAG_TEMPLATE.substitute(
        bg=TAG_BG[kind], fg=TAG_FG[kind], radius=RADIUS_SM,
        pad_x=SP_SM, font=FONT_SIZE_CAPTION)
    for kind in TAG_BG
}


def tag_style(kind: str) -> str:
    """状态标签的样式串；未知语义回落到 default（不抛，界面不该因新状态变空白）。

    用**显式样式串**而不是 QSS 动态属性：属性变更要 `unpolish`/`polish` 才生效，
    状态切换是高频路径，显式串最稳。
    """
    return _TAG_STYLES.get(kind, _TAG_STYLES["default"])


def dot_style(kind: str) -> str:
    """状态标签前的圆点色。"""
    return f"background:{TAG_DOT.get(kind, TAG_DOT['default'])};border-radius:3px;"


def make_mono(widget, point_size: int = 11) -> None:
    """等宽文本控件（机器码 / 激活码）：机器码里 `O` 和 `0`、`I` 和 `l` 要分得开。

    **只 `setFont()` 不管用**：全局 QSS 里 `QWidget { font-family: ... }` 的
    font-family 会盖掉控件自己设的字体族（Qt 里样式表的字体属性优先于控件字体，
    `setFont` 静默失效——本次重构真踩到，机器码从等宽变回了雅黑）。所以这里
    同时打 `objectName`，让 QSS 用 `#monoText` 这个更具体的选择器把族钉回等宽。
    字号仍由 `setFont` 给（QSS 没设 font-size，就沿用控件字体）。
    """
    font = QFont()
    font.setFamilies(list(MONO_FAMILIES))
    font.setPointSize(point_size)
    widget.setFont(font)
    widget.setObjectName("monoText")


def make_primary(button) -> None:
    """把按钮标成主按钮（QSS 选择器 `QPushButton[primary="true"]`）。

    QSS 在 polish 时读动态属性，改属性不会自动重刷样式，所以显式 unpolish/polish
    一次——控件若在样式表生效前就已构建，不这么做主色不会出现。
    """
    _mark(button, "primary")


def make_dashed(button) -> None:
    """把按钮标成虚线按钮——添加类弱操作（design-tokens §8）。"""
    _mark(button, "dashed")


def make_danger(button) -> None:
    """把按钮标成危险按钮——删除、驳回等破坏性操作（design-tokens §8）。"""
    _mark(button, "danger")


def _mark(button, prop: str) -> None:
    button.setProperty(prop, True)
    style = button.style()
    if style is not None:
        style.unpolish(button)
        style.polish(button)


_TOKENS = {
    "font_families": ", ".join(f'"{f}"' for f in FONT_FAMILIES) + ", sans-serif",
    "mono_families": ", ".join(f'"{f}"' for f in MONO_FAMILIES) + ", monospace",
    "font_body": FONT_SIZE_BODY,
    "font_caption": FONT_SIZE_CAPTION,
    "font_subtitle": FONT_SIZE_SUBTITLE,
    "font_title": FONT_SIZE_TITLE,
    "text_primary": TEXT_PRIMARY,
    "text_secondary": TEXT_SECONDARY,
    "text_tertiary": TEXT_TERTIARY,
    "text_disabled": TEXT_DISABLED,
    "border_base": BORDER_BASE,
    "border_split": BORDER_SPLIT,
    "fill_base": FILL_BASE,
    "bg_container": BG_CONTAINER,
    "bg_layout": BG_LAYOUT,
    "bg_header": BG_HEADER,
    "primary": PRIMARY,
    "primary_hover": PRIMARY_HOVER,
    "primary_active": PRIMARY_ACTIVE,
    "error_color": ERROR,
    "error_bg": TAG_BG["error"],
    "select_bg": SELECT_BG,
    "radius_sm": RADIUS_SM,
    "radius_md": RADIUS_MD,
    "radius_control": RADIUS_CONTROL,
    "radius_card": RADIUS_CARD,
    "sp_xs": SP_XS,
    "sp_sm": SP_SM,
    "sp_md": SP_MD,
    "sp_lg": SP_LG,
    "sp_xl": SP_XL,
    "sp_2xl": SP_2XL,
    # 按钮：内容高 22 + 上下 padding 4×2 + 边框 1×2 = 32px
    "control_h": 22,
    "btn_pad_y": SP_XS,
    "btn_pad_x": SP_LG,
}

QSS = Template("""
/* ============================ 基础 ============================ */
QWidget {
    font-family: $font_families;
    font-size: ${font_body}px;
    color: $text_primary;
}
QMainWindow { background: $bg_layout; }
QDialog { background: $bg_container; }
QWidget#appRoot { background: $bg_layout; }
QLabel { background: transparent; }

/* 文案层级：同层级字号全局唯一，禁止跳级 */
QLabel#appTitle     { font-size: ${font_title}px; font-weight: 600; color: $text_primary; }
QLabel#appSubtitle  { font-size: ${font_caption}px; color: $text_tertiary; }
QLabel#cardTitle    { font-size: ${font_subtitle}px; font-weight: 500; color: $text_primary; }
QLabel#sectionTitle { font-size: ${font_caption}px; color: $text_tertiary; }
QLabel#dialogTitle  { font-size: ${font_subtitle}px; font-weight: 500; color: $text_primary; }
QLabel#dialogHint   { font-size: ${font_caption}px; color: $text_tertiary; }
QLabel#emptyTitle   { font-size: ${font_subtitle}px; font-weight: 500; color: $text_secondary; }
QLabel#emptyHint    { font-size: ${font_caption}px; color: $text_tertiary; }

/* ============================ 分区容器 ============================ */
QFrame#appHeader, QFrame#appToolbar {
    background: $bg_container;
    border: none;
    border-bottom: 1px solid $border_split;
}
QFrame#vSeparator { background: $border_split; border: none; max-width: 1px; }
QFrame#hSeparator { background: $border_split; border: none; max-height: 1px; }
QFrame#cardPanel {
    background: $bg_container;
    border: 1px solid $border_split;
    border-radius: ${radius_card}px;
}
QFrame#characterCard {
    background: $bg_container;
    border: 1px solid $border_split;
    border-radius: ${radius_card}px;
}

/* ============================ 按钮层级 ============================ */
/* 次按钮（默认）：白底 + 灰描边 */
QPushButton {
    background: $bg_container;
    border: 1px solid $border_base;
    border-radius: ${radius_control}px;
    padding: ${btn_pad_y}px ${btn_pad_x}px;
    min-height: ${control_h}px;
    color: $text_primary;
}
QPushButton:hover  { border-color: $primary_hover; color: $primary; }
QPushButton:pressed { border-color: $primary_active; color: $primary_active; }
QPushButton:disabled {
    background: $fill_base; border-color: $border_base; color: $text_disabled;
}
/* 主按钮：页面唯一主操作 */
QPushButton[primary="true"] {
    background: $primary; border: 1px solid $primary;
    color: #FFFFFF; font-weight: 500;
}
QPushButton[primary="true"]:hover {
    background: $primary_hover; border-color: $primary_hover; color: #FFFFFF;
}
QPushButton[primary="true"]:pressed {
    background: $primary_active; border-color: $primary_active; color: #FFFFFF;
}
QPushButton[primary="true"]:disabled {
    background: $fill_base; border-color: $border_base; color: $text_disabled;
}
/* 虚线按钮：添加类弱操作（新增一行 / 添加筛选） */
QPushButton[dashed="true"] { border-style: dashed; }
/* 危险按钮：删除、驳回等破坏性操作 */
QPushButton[danger="true"] { border-color: $error_color; color: $error_color; }
QPushButton[danger="true"]:hover {
    background: $error_bg; border-color: $error_color; color: $error_color;
}

/* ============================ 输入控件 ============================ */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: $bg_container;
    border: 1px solid $border_base;
    border-radius: ${radius_md}px;
    padding: ${btn_pad_y}px $sp_sm;
    min-height: ${control_h}px;
    color: $text_primary;
    selection-background-color: $select_bg;
    selection-color: $text_primary;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: $primary_hover;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background: $fill_base; color: $text_disabled;
}
QLineEdit[readOnly="true"] { background: $bg_header; }

/* 下拉箭头**完全交给 Fusion 画**，一条 ::drop-down / ::down-arrow 规则都不给。
   两条路都试过、都不行：
   - 照抄 CSS 的「0 尺寸盒子 + 三边透明边框」三角画法 → Qt 的 ::down-arrow 只认
     `image:`，不实现这套 hack，渲染出来是一个实心方块；
   - 只给 ::drop-down 去描边 → 箭头**整个消失**（QStyleSheetStyle 一旦接管这个
     子控件，就不再用基础样式的箭头图元）。
   代价是 Fusion 会在右侧画一道淡淡的下拉按钮分隔线，比丢箭头划算得多。 */
QComboBox QAbstractItemView {
    background: $bg_container;
    border: 1px solid $border_split;
    border-radius: ${radius_md}px;
    selection-background-color: $select_bg;
    selection-color: $text_primary;
    outline: none;
}

/* 复选框指示器**不碰**：QSS 一旦接管 indicator 而不给图片，未勾选的框会整个消失。
   交给 Fusion 画。 */
QCheckBox { spacing: $sp_sm; }
QCheckBox:disabled { color: $text_disabled; }

/* ============================ 文本域 / 日志 ============================ */
QPlainTextEdit {
    background: $bg_header;
    border: 1px solid $border_split;
    border-radius: ${radius_md}px;
    padding: $sp_sm;
    color: $text_primary;
    selection-background-color: $select_bg;
    selection-color: $text_primary;
}
QPlainTextEdit#logView {
    font-family: $mono_families;
    font-size: ${font_caption}px;
    color: $text_secondary;
}
QPlainTextEdit#yamlView { font-family: $mono_families; font-size: ${font_caption}px; }
/* 机器码 / 激活码：族必须在这里钉死。控件自己 setFont 是**盖不过**
   `QWidget { font-family }` 的（样式表字体属性优先），所以走 objectName。 */
QLineEdit#monoText, QPlainTextEdit#monoText { font-family: $mono_families; }

/* ============================ 列表 / 表格 / 树 ============================ */
QListWidget, QTableWidget, QTreeWidget {
    background: $bg_container;
    border: 1px solid $border_split;
    border-radius: ${radius_md}px;
    outline: none;
    selection-background-color: $select_bg;
    selection-color: $text_primary;
}
QListWidget::item { padding: ${sp_sm}px; border-radius: ${radius_sm}px; }
QListWidget::item:hover { background: $fill_base; }
QListWidget::item:selected { background: $select_bg; color: $text_primary; }

QTableWidget { gridline-color: $border_split; }
QTableWidget::item { padding: ${sp_sm}px; }
QTableWidget::item:selected { background: $select_bg; color: $text_primary; }
QHeaderView { background: $bg_header; border: none; }
QHeaderView::section {
    background: $bg_header;
    color: $text_primary;
    font-weight: 500;
    border: none;
    border-bottom: 1px solid $border_split;
    border-right: 1px solid $border_split;
    padding: $sp_sm $sp_lg;
}

/* 左树：选中态走主色系，不用系统蓝 */
QTreeWidget#configTree {
    border: none;
    border-right: 1px solid $border_split;
    border-radius: 0;
    background: $bg_container;
}
QTreeWidget#configTree::item { height: 36px; padding-left: $sp_sm; }
QTreeWidget#configTree::item:hover { background: $fill_base; }
QTreeWidget#configTree::item:selected { background: $select_bg; color: $primary_active; }

/* ============================ 分组框 ============================ */
QGroupBox {
    background: $bg_container;
    border: 1px solid $border_split;
    border-radius: ${radius_card}px;
    margin-top: ${sp_md}px;
    padding: $sp_lg $sp_lg ${sp_md}px $sp_lg;
    font-weight: 500;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: $sp_lg;
    padding: 0 $sp_xs;
    background: $bg_container;
    color: $text_primary;
}

/* ============================ 滚动区 ============================ */
QScrollArea { border: none; background: transparent; }
QScrollArea#cardArea, QScrollArea#cardArea > QWidget > QWidget { background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

QScrollBar:vertical {
    background: transparent; width: 10px; margin: 0;
}
QScrollBar::handle:vertical {
    background: $border_base; border-radius: 5px; min-height: ${sp_2xl}px;
}
QScrollBar::handle:vertical:hover { background: $text_disabled; }
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 0;
}
QScrollBar::handle:horizontal {
    background: $border_base; border-radius: 5px; min-width: ${sp_2xl}px;
}
QScrollBar::handle:horizontal:hover { background: $text_disabled; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ============================ 状态栏 ============================ */
QStatusBar {
    background: $bg_container;
    border-top: 1px solid $border_split;
    color: $text_secondary;
    min-height: ${sp_xl}px;
}
QStatusBar::item { border: none; }
""")


def apply_theme(app) -> None:
    """给 QApplication 装主题：Fusion 样式 + 全局字体 + 全局 QSS。

    必须在**创建任何控件之前**调用——QSS 在 polish 时读取动态属性，
    控件先建好再上样式，`[primary="true"]` 这类选择器不生效。
    """
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(list(FONT_FAMILIES))
    font.setPixelSize(FONT_SIZE_BODY)
    app.setFont(font)
    app.setStyleSheet(QSS.substitute(_TOKENS))
