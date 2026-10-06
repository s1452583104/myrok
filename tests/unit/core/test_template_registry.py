from pathlib import Path
import shutil
import cv2
import numpy as np
import pytest
from rok_assistant.core.template_registry import TemplateRegistry, TemplateSpec, ROI

FIX = Path(__file__).parent.parent.parent / "fixtures"

@pytest.fixture
def manifest_with_png(tmp_path):
    # Create stub template files
    (tmp_path / "btn_a.png").write_bytes(b"")
    (tmp_path / "btn_b.png").write_bytes(b"")
    (tmp_path / "card.onnx").write_bytes(b"")
    # Copy manifest
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text((FIX / "manifest_test.yaml").read_text())
    return manifest

def test_load_manifest(manifest_with_png):
    reg = TemplateRegistry.load(manifest_with_png)
    assert "btn_a" in reg
    assert "btn_b" in reg
    assert "card" in reg

def test_get_template_spec(manifest_with_png):
    reg = TemplateRegistry.load(manifest_with_png)
    spec = reg.get("btn_a")
    assert isinstance(spec, TemplateSpec)
    assert spec.threshold == 0.9
    assert spec.roi.x1 == 10

def test_roi_full(manifest_with_png):
    reg = TemplateRegistry.load(manifest_with_png)
    spec = reg.get("btn_b")
    assert spec.roi.is_full

def test_template_spec_type(manifest_with_png):
    reg = TemplateRegistry.load(manifest_with_png)
    spec = reg.get("card")
    assert spec.type == "yolo_detect"

@pytest.fixture
def image_manifest(tmp_path):
    # Manifest referencing a real (loadable) template image
    shutil.copy(FIX / "template_search.png", tmp_path / "template_search.png")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "templates:\n"
        "  - id: search\n"
        "    file: template_search.png\n"
        "    roi: full\n"
        "    threshold: 0.9\n"
        "  - id: search_roi\n"
        "    file: template_search.png\n"
        "    roi: [0, 0, 80, 80]\n"
        "    threshold: 0.9\n"
    )
    return manifest

def test_build_recognizers_returns_template_matches(image_manifest):
    from rok_assistant.core.recognizers.template_match import TemplateMatch
    reg = TemplateRegistry.load(image_manifest)
    recs = reg.build_recognizers()
    assert set(recs) == {"search", "search_roi"}
    assert all(isinstance(r, TemplateMatch) for r in recs.values())
    img = cv2.imread(str(FIX / "screenshot_with_template.png"))
    # full-screen ROI -> roi=None in the recognizer
    r = recs["search"].recognize(img)
    assert r.matched
    assert abs(r.bbox.x1 - 40) < 2
    # bounded ROI -> BBox, coords back in global image space
    r2 = recs["search_roi"].recognize(img)
    assert r2.matched
    assert abs(r2.bbox.x1 - 40) < 2

def test_build_recognizers_missing_image_raises(manifest_with_png):
    # btn_a.png is a stub of empty bytes -> cv2.imread returns None
    reg = TemplateRegistry.load(manifest_with_png)
    with pytest.raises(FileNotFoundError):
        reg.build_recognizers()

def test_build_recognizers_rejects_yolo(tmp_path):
    (tmp_path / "card.onnx").write_bytes(b"")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "templates:\n"
        "  - id: card\n"
        "    file: card.onnx\n"
        "    type: yolo_detect\n"
        "    classes: [0]\n"
        "    threshold: 0.7\n"
    )
    reg = TemplateRegistry.load(manifest)
    with pytest.raises(ValueError, match="unsupported template type for card: yolo_detect"):
        reg.build_recognizers()


def test_templates_load_from_non_ascii_path(tmp_path):
    """中文路径下模板必须能加载。

    cv2.imread 在 Windows 的非 ASCII 路径上静默返回 None；用户把绿色包解压到
    「D:\\游戏\\rok-assistant」这类目录时，53 张模板会集体加载失败。
    这条测试就是钉住 imread_unicode 那个绕法。
    """
    zh_dir = tmp_path / "游戏" / "rok-assistant"
    zh_dir.mkdir(parents=True)
    png = zh_dir / "btn_a.png"
    ok, buf = cv2.imencode(".png", np.full((8, 8, 3), 128, dtype=np.uint8))
    assert ok
    png.write_bytes(buf.tobytes())
    (zh_dir / "manifest.yaml").write_text(
        "templates:\n"
        "  - id: btn_a\n"
        "    file: btn_a.png\n"
        "    threshold: 0.9\n",
        encoding="utf-8")

    reg = TemplateRegistry.load(zh_dir / "manifest.yaml")
    recognizers = reg.build_recognizers()
    assert "btn_a" in recognizers


# ---- 三识别栈融合（2026-09-17）：Chain(模板→YOLO/OCR 兜底) 装配 ----

class _FakeBoxes:
    def __init__(self, rows):
        self._rows = rows
    def __iter__(self):
        return iter(self._rows)
    def __len__(self):
        return len(self._rows)

class _FakeBox:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = [np.array(xyxy, dtype=float)]
        self.conf = [conf]
        self.cls = [cls]

class _FakeResult:
    def __init__(self, rows):
        # 行格式 (x1, y1, x2, y2, conf[, cls])，cls 缺省 0
        self.boxes = _FakeBoxes(
            [_FakeBox(r[:4], r[4], r[5] if len(r) > 5 else 0) for r in rows])

class _FakeSharedYolo:
    """Stub SharedYoloDetector: fixed detections, class-name -> id 0..n order."""
    def __init__(self, rows, names):
        self._rows = rows
        self.names = names
    def detect(self, frame):
        return [_FakeResult(self._rows)]


class _StubOcrEngine:
    """Stub RapidOcrEngine：记录被喂进来的帧形状，返回固定几行文本。"""
    def __init__(self, lines=()):
        self.queries = []
        self._lines = list(lines)
    def detect_text(self, frame):
        from rok_assistant.core.recognizer import BBox
        self.queries.append(frame.shape)
        return [(BBox(10, 10, 100, 30), text, conf) for text, conf in self._lines]

def test_build_recognizers_yolo_fallback_chain(image_manifest):
    from rok_assistant.core.recognizer import RecognizerChain
    reg = TemplateRegistry.load(image_manifest)
    recs = reg.build_recognizers(
        yolo_shared=_FakeSharedYolo([], {0: "search", 1: "search_roi"}))
    assert set(recs) == {"search", "search_roi"}
    assert all(isinstance(r, RecognizerChain) for r in recs.values())
    img = cv2.imread(str(FIX / "template_search.png"))  # 模板自身命中 -> 主路径
    r = recs["search"].recognize(cv2.imread(str(FIX / "screenshot_with_template.png")))
    assert r.matched

def test_yolo_fallback_fires_when_template_misses(image_manifest):
    reg = TemplateRegistry.load(image_manifest)
    # 模板在纯灰底上不命中 -> YOLO 兜底命中（fake 返回 0.9 置信框）
    fake = _FakeSharedYolo([(10, 10, 30, 30, 0.9)], {0: "search", 1: "search_roi"})
    recs = reg.build_recognizers(yolo_shared=fake)
    img = np.full((200, 200, 3), 128, dtype=np.uint8)
    r = recs["search"].recognize(img)
    assert r.matched
    assert r.bbox.x1 == 10

def test_yolo_threshold_decoupled_from_template(image_manifest):
    """YOLO 用自己的 yolo_threshold（默认 0.5），不再共用模板的 0.9。

    2026-10-04 改语义：旧版这里断言「YOLO 0.6 < 模板阈值 0.9 -> 整链未命中」，
    那条耦合正是本次要去掉的——TM_CCOEFF_NORMED 和 YOLO conf 是两把尺子。
    """
    from rok_assistant.core.template_registry import DEFAULT_YOLO_THRESHOLD
    assert DEFAULT_YOLO_THRESHOLD == 0.5
    reg = TemplateRegistry.load(image_manifest)          # 模板阈值 0.9
    img = np.full((200, 200, 3), 128, dtype=np.uint8)
    # 0.6 >= 0.5 -> YOLO 命中（旧语义下会被模板的 0.9 拦掉）
    recs = reg.build_recognizers(
        yolo_shared=_FakeSharedYolo([(10, 10, 30, 30, 0.6)], {0: "search"}))
    r = recs["search"].recognize(img)
    assert r.matched and r.bbox.x1 == 10
    # 低于 YOLO 阈值 -> 整链不命中（模板在灰底上也不命中）
    recs2 = reg.build_recognizers(
        yolo_shared=_FakeSharedYolo([(10, 10, 30, 30, 0.4)], {0: "search"}))
    assert not recs2["search"].recognize(img).matched


def test_yolo_wins_over_a_matching_template(image_manifest):
    """YOLO 优先：模板同样命中时，返回的是 YOLO 的框（顺序反转的锚点）。"""
    reg = TemplateRegistry.load(image_manifest)
    fake = _FakeSharedYolo([(50, 60, 90, 100, 0.7)], {0: "search", 1: "search_roi"})
    recs = reg.build_recognizers(yolo_shared=fake)
    img = cv2.imread(str(FIX / "screenshot_with_template.png"))   # 模板会命中
    r = recs["search"].recognize(img)
    assert r.matched
    assert r.recognizer_id == "search@yolo"      # 不是模板腿
    assert r.bbox.x1 == 50


def test_yolo_threshold_override_can_disable_the_leg(image_manifest):
    """条目写 yolo_threshold: 1.01 = 关掉 YOLO 腿（preset_* / alliance_btn 用）。

    定标实测这两类 YOLO 不可用：preset_* 漏检（640 输入下图标约 15px），
    alliance_btn 漏检 + 真误报 0.480。它们都要点击，假阳性 = 点错位置。
    """
    manifest = image_manifest.parent / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8")
                        + "  - id: search_off\n    file: template_search.png\n"
                          "    roi: full\n    threshold: 0.9\n"
                          "    yolo_threshold: 1.01\n", encoding="utf-8")
    reg = TemplateRegistry.load(manifest)
    assert reg.get("search_off").yolo_threshold == 1.01
    assert reg.get("search").yolo_threshold is None      # 未写的条目吃默认
    fake = _FakeSharedYolo([(50, 60, 90, 100, 0.99, 2)],
                           {0: "search", 1: "search_roi", 2: "search_off"})
    recs = reg.build_recognizers(yolo_shared=fake)
    img = np.full((200, 200, 3), 128, dtype=np.uint8)
    assert not recs["search_off"].recognize(img).matched   # 0.99 < 1.01 -> 腿关闭


def test_fill_leg_stays_template_first(image_manifest):
    """fill_ 的兜底腿是 OCR，不该被「YOLO 优先」波及——保持模板先行。"""
    from rok_assistant.core.recognizers.ocr_text import OCRText
    from rok_assistant.core.recognizers.template_match import TemplateMatch

    class _StubOcr:
        def detect_text(self, frame):
            return []

    manifest = image_manifest.parent / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8")
                        + "  - id: fill_阑珊填1\n    file: template_search.png\n"
                          "    roi: [0, 0, 80, 80]\n    threshold: 0.9\n",
                        encoding="utf-8")
    reg = TemplateRegistry.load(manifest)
    recs = reg.build_recognizers(yolo_shared=_FakeSharedYolo([], {0: "search"}),
                                 ocr_engine=_StubOcr())
    legs = recs["fill_阑珊填1"]._recognizers
    assert isinstance(legs[0], TemplateMatch)     # 模板仍是第一腿
    assert isinstance(legs[1], OCRText)

def test_yolo_spec_builds_adapter_with_model(image_manifest):
    manifest = image_manifest.parent / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8")
                        + "  - id: card\n    file: card.onnx\n"
                          "    type: yolo_detect\n    classes: [0]\n"
                          "    threshold: 0.7\n", encoding="utf-8")
    reg = TemplateRegistry.load(manifest)
    fake = _FakeSharedYolo([(10, 10, 30, 30, 0.8)], {0: "whatever"})
    recs = reg.build_recognizers(yolo_shared=fake)
    r = recs["card"].recognize(np.zeros((100, 100, 3), dtype=np.uint8))
    assert r.matched and abs(r.confidence - 0.8) < 1e-6


def test_yolo_fallback_skipped_when_class_not_in_model(image_manifest):
    # queue_recall_icon 类被 YOLO 排除训练：模板为主，不挂兜底
    # （挂了运行时 resolve 类名会 KeyError）
    reg = TemplateRegistry.load(image_manifest)
    recs = reg.build_recognizers(yolo_shared=_FakeSharedYolo([], {0: "unrelated"}))
    from rok_assistant.core.recognizers.template_match import TemplateMatch
    assert isinstance(recs["search"], TemplateMatch)
    # 类在模型里的 id 正常挂兜底
    recs2 = reg.build_recognizers(yolo_shared=_FakeSharedYolo([], {0: "search"}))
    from rok_assistant.core.recognizer import RecognizerChain
    assert isinstance(recs2["search"], RecognizerChain)


def test_fill_spec_gets_ocr_fallback(image_manifest):
    manifest = image_manifest.parent / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8")
                        + "  - id: fill_Jy丶阑珊\n    file: template_search.png\n"
                          "    roi: [460, 240, 760, 660]\n    threshold: 0.9\n",
                        encoding="utf-8")
    from rok_assistant.core.recognizers.ocr_text import OCRText

    class StubOcrEngine:
        def __init__(self):
            self.queries = []
        def detect_text(self, frame):
            self.queries.append(frame.shape)
            from rok_assistant.core.recognizer import BBox
            return [(BBox(10, 10, 100, 30), "某某 [482A]Jy丶阑珊", 0.93)]

    engine = StubOcrEngine()
    reg = TemplateRegistry.load(manifest)
    recs = reg.build_recognizers(yolo_shared=_FakeSharedYolo([], {}),
                                 ocr_engine=engine)
    # 模板命中与否未知（灰底大概率未命中）→ OCR 兜底按名字文本命中
    img = np.full((700, 800, 3), 128, dtype=np.uint8)
    r = recs["fill_Jy丶阑珊"].recognize(img)
    assert r.matched
    assert "Jy丶阑珊" in r.data["text"]
    assert len(engine.queries) >= 1

def test_fill_spec_gets_ocr_leg_without_yolo_model(image_manifest):
    """ocr_name_fallback 是独立开关：没配 yolo_model 也该给 fill_ 挂 OCR 腿。

    旧行为把 OCR 腿嵌在 `if shared_yolo is not None` 里，纯模板模式下
    `ocr_name_fallback: true` 静默失效——名字类判据本来就与 YOLO 无关
    （YOLO 不训这类），不该被「配没配 YOLO」二次门控。
    """
    from rok_assistant.core.recognizers.ocr_text import OCRText
    from rok_assistant.core.recognizers.template_match import TemplateMatch
    manifest = image_manifest.parent / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8")
                        + "  - id: fill_某人\n    file: template_search.png\n"
                          "    roi: [460, 240, 760, 660]\n    threshold: 0.9\n",
                        encoding="utf-8")
    reg = TemplateRegistry.load(manifest)
    recs = reg.build_recognizers(ocr_engine=_StubOcrEngine())   # 不传 yolo_model
    legs = recs["fill_某人"]._recognizers
    assert isinstance(legs[0], TemplateMatch)     # 模板仍先行
    assert isinstance(legs[1], OCRText)


# ---- 配置驱动的车头判据（2026-10-06）：换车头不该需要改 manifest ----

def test_config_fill_name_without_manifest_gets_ocr_recognizer(image_manifest):
    """配置点名的车头在 manifest 里没有条目时，就地生成 OCR 判据。

    车头名是账号/配置绑定的，manifest 是随包走的静态资源：用户随时改
    `fill_target_leaders` 换车头，manifest 不会自动多出一条。旧行为下
    MemberStateMachine 只打一条 warning，然后 `_find` 永远 None、60 次
    轮询空转到 no_rally_found——改配置等于静默失效。
    """
    from rok_assistant.core.recognizers.ocr_text import OCRText
    engine = _StubOcrEngine(lines=[("某某 [482A]新車頭", 0.93)])
    reg = TemplateRegistry.load(image_manifest)

    recs = reg.build_recognizers(ocr_engine=engine, fill_names=["新車頭"])

    assert "fill_新車頭" in recs
    assert isinstance(recs["fill_新車頭"], OCRText)
    img = np.full((1080, 1920, 3), 128, dtype=np.uint8)
    r = recs["fill_新車頭"].recognize(img)
    assert r.matched and r.data["text"] == "某某 [482A]新車頭"
    # 名字列 ROI 必须生效：全屏 OCR 会把聊天框里的同名文本也当成目标行，
    # 然后按固定几何点到一片空地上。420x300 = 实测名字列 460,240,760,660
    assert engine.queries == [(420, 300, 3)]


def test_manifest_fill_entry_wins_over_config_generated(image_manifest):
    """manifest 里已有的 fill_ 条目仍走「模板先行 + OCR 兜底」，不被顶掉。"""
    from rok_assistant.core.recognizers.ocr_text import OCRText
    from rok_assistant.core.recognizers.template_match import TemplateMatch
    manifest = image_manifest.parent / "manifest.yaml"
    manifest.write_text(image_manifest.read_text(encoding="utf-8")
                        + "  - id: fill_阑珊寨子号\n    file: template_search.png\n"
                          "    roi: [460, 240, 760, 660]\n    threshold: 0.9\n",
                        encoding="utf-8")
    reg = TemplateRegistry.load(manifest)

    recs = reg.build_recognizers(ocr_engine=_StubOcrEngine(),
                                 fill_names=["阑珊寨子号"])

    legs = recs["fill_阑珊寨子号"]._recognizers
    assert isinstance(legs[0], TemplateMatch)
    assert isinstance(legs[1], OCRText)


def test_config_fill_name_skipped_when_ocr_fallback_disabled(image_manifest):
    """ocr_name_fallback: false 时不该凭空生成 OCR 判据。"""
    reg = TemplateRegistry.load(image_manifest)

    recs = reg.build_recognizers(ocr_engine=_StubOcrEngine(),
                                 fill_names=["新車頭"], ocr_fallback=False)

    assert "fill_新車頭" not in recs


def test_fill_recognizers_share_a_single_ocr_engine(image_manifest, monkeypatch):
    """RapidOCR 是重资源：一次装配只建一个后端，多个 fill_ id 共用。

    每个 id 各建一个后端会让同一帧被反复推理（RapidOcrEngine 的单帧缓存
    是挂在后端上的，见其 docstring）。
    """
    import rok_assistant.core.recognizers.ocr_text as ocr_mod
    made = []

    class _Counting(ocr_mod.RapidOcrEngine):
        def __init__(self):
            super().__init__()
            made.append(self)

    monkeypatch.setattr(ocr_mod, "RapidOcrEngine", _Counting)
    reg = TemplateRegistry.load(image_manifest)

    reg.build_recognizers(fill_names=["甲", "乙"])

    assert len(made) == 1


def test_build_recognizers_rejects_an_unknown_type(tmp_path):
    """真正未知的 type 走 else 分支——`yolo_detect` 那条测的是另一个分支。"""
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "templates:\n"
        "  - id: weird\n"
        "    file: whatever.png\n"
        "    type: nonsense\n"
        "    threshold: 0.9\n"
    )
    reg = TemplateRegistry.load(manifest)
    with pytest.raises(ValueError, match="unsupported template type for weird: nonsense"):
        reg.build_recognizers()


# ---- pixel_stats 小节（2026-09-27）：选中态改走像素判据 ----

@pytest.fixture
def manifest_with_pixel_stats(image_manifest):
    manifest = image_manifest.parent / "manifest.yaml"
    manifest.write_text(image_manifest.read_text(encoding="utf-8")
                        + "pixel_stats:\n"
                          "  - id: selected_preset_1\n    kind: preset_slot\n"
                          "  - id: selected_preset_2\n    kind: preset_slot\n",
                        encoding="utf-8")
    return manifest


def test_pixel_stats_build_recognizers_alongside_templates(manifest_with_pixel_stats):
    from rok_assistant.core.recognizers.pixel_stat import PixelStatRecognizer
    reg = TemplateRegistry.load(manifest_with_pixel_stats)

    recs = reg.build_recognizers()

    assert set(recs) == {"search", "search_roi",
                         "selected_preset_1", "selected_preset_2"}
    assert isinstance(recs["selected_preset_1"], PixelStatRecognizer)


def test_pixel_stats_do_not_enter_the_template_table(manifest_with_pixel_stats):
    """爆炸半径不变量：pixel_stats 的 id 绝不进 `_t`。

    `_t` 会被 auto_label_yolo / ingest_raw_imgs 逐个 cv2.imread(spec.file)。
    """
    reg = TemplateRegistry.load(manifest_with_pixel_stats)
    assert set(reg._t) == {"search", "search_roi"}
    assert [s.id for s in reg._pixel] == ["selected_preset_1", "selected_preset_2"]


def test_manifest_without_pixel_stats_section_still_works(image_manifest):
    """没写 pixel_stats 的 manifest（旧部署/测试 fixture）照常装配。"""
    reg = TemplateRegistry.load(image_manifest)
    assert reg._pixel == []
    assert set(reg.build_recognizers()) == {"search", "search_roi"}


def test_pixel_stats_rejects_an_unknown_kind(image_manifest):
    manifest = image_manifest.parent / "manifest.yaml"
    manifest.write_text(image_manifest.read_text(encoding="utf-8")
                        + "pixel_stats:\n"
                          "  - id: selected_preset_1\n    kind: nonsense\n",
                        encoding="utf-8")
    reg = TemplateRegistry.load(manifest)
    with pytest.raises(ValueError, match="unsupported pixel_stat kind for "
                                         "selected_preset_1: nonsense"):
        reg.build_recognizers()
