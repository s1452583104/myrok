import pytest
from pydantic import ValidationError
from rok_assistant.infra.config import (
    AppConfig, InstanceConfig, CharacterConfig, RoleEnum, FillLeader, RootConfig,
    RAIDER_TARGET, find_level_collisions, level_range,
    AppMode, IMPLEMENTED_MODES, MODE_LABELS, ModeConfig, ZhaiduoConfig,
    QuizConfig, QuizLLMConfig, QuizInstanceConfig, GemInstanceConfig,
    GemCharacterConfig, NoRoleInstanceConfig, NoRoleCharacterConfig,
)


def _leader_inst() -> dict:
    """最小可加载的 leader 实例（dict 形态，喂给 RootConfig 的模式段）。"""
    return {"id": "i1", "mumu_index": 0,
            "characters": [{"id": "c1", "name": "Hero", "role": "leader",
                            "target_levels": [8], "march_preset": 1,
                            "march_troop_types": ["infantry"]}]}


def _leader(**kw):
    base = dict(id="c1", name="Hero", role=RoleEnum.LEADER, target_levels=[8],
                march_preset=1, march_troop_types=["infantry"])
    base.update(kw)
    return CharacterConfig(**base)


def _member(**kw):
    base = dict(id="c2", name="M1", role=RoleEnum.MEMBER, target_levels=[5],
                march_preset=2, march_troop_types=["cavalry"],
                fill_target_leaders=[FillLeader(instance="i1", name="Hero")])
    base.update(kw)
    return CharacterConfig(**base)


def _root(*characters) -> RootConfig:
    return RootConfig(zhaiduo={"instances": [InstanceConfig(
        id="i1", mumu_index=0, characters=list(characters))]})


# ---- 模式分区（2026-10-13）----

def test_app_mode_values_are_ascii_identifiers():
    assert [m.value for m in AppMode] == ["zhaiduo", "gem", "quiz"]


def test_mode_labels_cover_every_mode():
    assert set(MODE_LABELS) == set(AppMode)
    assert MODE_LABELS[AppMode.ZHAIDUO] == "寨多多模式"
    assert MODE_LABELS[AppMode.GEM] == "宝石模式"
    assert MODE_LABELS[AppMode.QUIZ] == "答题模式"


def test_implemented_modes_cover_every_mode():
    """已实现的模式清单：改它等于改「界面上哪些模式可点」。
    2026-10-24 起三个模式全部落地，所以直接等于 `AppMode` 全集——
    将来再加模式时，这条会在忘记改 `IMPLEMENTED_MODES` 时先红。"""
    assert IMPLEMENTED_MODES == frozenset(AppMode)


def test_gem_and_quiz_may_be_empty():
    """宝石/答题的实例段可空：配不出角色也不该加载失败。"""
    cfg = RootConfig(zhaiduo={"instances": [_leader_inst()]})
    assert cfg.gem.instances == []
    assert cfg.quiz.instances == []


def test_zhaiduo_requires_at_least_one_instance():
    with pytest.raises(ValidationError):
        RootConfig(zhaiduo={"instances": []})


def test_instances_for_returns_that_modes_instances():
    cfg = RootConfig(zhaiduo={"instances": [_leader_inst()]})
    assert cfg.instances_for(AppMode.ZHAIDUO) == cfg.zhaiduo.instances
    assert cfg.instances_for(AppMode.GEM) == []


def test_legacy_flat_instances_gives_actionable_error():
    """老配置（顶层 instances）不能只说 Field required —— 要告诉用户怎么办。"""
    with pytest.raises(ValidationError) as ei:
        RootConfig.model_validate({"app": {}, "instances": []})
    assert "请删除 config.yaml 后重启" in str(ei.value)


def test_leader_minimal():
    c = _leader()
    assert c.role == RoleEnum.LEADER
    assert c.fill_target_leaders == []


def test_member_requires_fill_targets():
    with pytest.raises(ValidationError, match="必须配置"):
        _root(_leader(), _member(fill_target_leaders=[]))


def test_either_role_roundtrip():
    cfg = _root(_leader(),
                _member(id="c3", name="F1", role=RoleEnum.EITHER))
    either = cfg.zhaiduo.instances[0].characters[1]
    assert either.role == RoleEnum.EITHER
    assert either.fill_target_leaders[0].name == "Hero"


def test_either_requires_fill_targets():
    with pytest.raises(ValidationError, match="必须配置"):
        _root(_leader(), _member(id="c3", name="F1", role=RoleEnum.EITHER,
                                 fill_target_leaders=[]))


def test_leader_must_not_have_fill_targets():
    with pytest.raises(ValidationError, match="不能配置"):
        _root(_leader(fill_target_leaders=[FillLeader(instance="i1", name="X")]))


def test_instance_requires_leader_or_either():
    with pytest.raises(ValidationError, match="整个配置至少需要"):
        _root(_member(id="c9", name="OnlyM"))


def test_instance_duplicate_names():
    with pytest.raises(ValidationError, match="duplicate"):
        _root(_leader(), _member(name="Hero"))


def test_mumu_and_adb_both_set_rejected():
    with pytest.raises(ValidationError, match="只能填一个"):
        RootConfig(zhaiduo={"instances": [InstanceConfig(
            id="i1", mumu_index=0, adb_address="127.0.0.1:16384",
            characters=[_leader()])]})


def test_mumu_and_adb_both_empty_rejected():
    with pytest.raises(ValidationError, match="必须填一个"):
        RootConfig(zhaiduo={"instances": [InstanceConfig(id="i1", characters=[_leader()])]})


def test_window_title_pattern_optional():
    inst = InstanceConfig(id="i1", mumu_index=0, characters=[_leader()])
    assert inst.window_title_pattern == ""


def test_fill_target_must_exist():
    with pytest.raises(ValidationError, match="不存在"):
        _root(_leader(),
              _member(fill_target_leaders=[FillLeader(instance="i1", name="Ghost")]))


def test_fill_target_must_be_leader_or_either():
    with pytest.raises(ValidationError, match="leader/either"):
        _root(_leader(), _member(),
              _member(id="c3", name="M2",
                      fill_target_leaders=[FillLeader(instance="i1", name="M1")]))


def test_cross_instance_fill_target_ok():
    a = InstanceConfig(id="i1", mumu_index=0, characters=[_leader()])
    b = InstanceConfig(id="i2", mumu_index=1,
                       characters=[_member(fill_target_leaders=[FillLeader(instance="i1", name="Hero")])])
    cfg = RootConfig(zhaiduo={"instances": [a, b]})
    assert cfg.zhaiduo.instances[1].characters[0].fill_target_leaders[0].instance == "i1"


def test_duplicate_instance_ids():
    with pytest.raises(ValidationError, match="实例 id 重复"):
        RootConfig(zhaiduo={"instances": [
            InstanceConfig(id="i1", mumu_index=0, characters=[_leader()]),
            InstanceConfig(id="i1", mumu_index=1, characters=[_leader(id="c9", name="H2")])]})


def test_duplicate_character_ids():
    with pytest.raises(ValidationError, match="角色 id 重复"):
        RootConfig(zhaiduo={"instances": [
            InstanceConfig(id="i1", mumu_index=0, characters=[_leader()]),
            InstanceConfig(id="i2", mumu_index=1, characters=[_leader(name="H2")])]})


def test_app_config_mumu_fields():
    app = AppConfig()
    assert app.mumu_manager_path == ""
    assert app.adb_path == "adb"


# ---- target_levels 多选（2026-10-04）----

def test_target_levels_order_is_preserved():
    """顺序完全自由（用户明确要求 6→4→5 合法）：校验不得重排。"""
    c = _leader(target_levels=[6, 4, 5])
    assert c.target_levels == [6, 4, 5]


def test_target_levels_empty_rejected():
    with pytest.raises(ValidationError, match="不能为空"):
        _leader(target_levels=[])


def test_target_levels_too_many_rejected():
    with pytest.raises(ValidationError, match="最多 3 个"):
        _leader(target_levels=[8, 7, 6, 5])


def test_target_levels_out_of_range_rejected():
    with pytest.raises(ValidationError, match="1..15"):
        _leader(target_levels=[16])


def test_target_levels_duplicate_rejected():
    with pytest.raises(ValidationError, match="有重复"):
        _leader(target_levels=[7, 7])


def test_target_levels_three_is_allowed():
    assert _leader(target_levels=[9, 8, 7]).target_levels == [9, 8, 7]


# ---- 等级区间 1–10 / 11–15 互斥（2026-10-13）----

def test_level_range_splits_at_ten():
    assert level_range(1) == (1, 10)
    assert level_range(10) == (1, 10)
    assert level_range(11) == (11, 15)
    assert level_range(15) == (11, 15)


def test_target_levels_allows_ten_itself():
    """边界值 10 属于低区间，不是「越界」。"""
    assert _leader(target_levels=[10]).target_levels == [10]


def test_target_levels_accepts_the_high_range():
    assert _leader(target_levels=[15, 13, 11]).target_levels == [15, 13, 11]


def test_target_levels_rejects_16():
    with pytest.raises(ValidationError, match="1..15"):
        _leader(target_levels=[16])


def test_target_levels_rejects_mixed_ranges():
    """面板同一时刻只能停在一个区间上，混选没有意义。"""
    with pytest.raises(ValidationError, match="不能混选两个等级区间"):
        _leader(target_levels=[9, 11])


def test_target_levels_rejects_mixed_ranges_regardless_of_order():
    with pytest.raises(ValidationError, match="不能混选两个等级区间"):
        _leader(target_levels=[12, 9])


# ---- 劫掠者寨子（2026-10-11）----

def test_raider_target_alone_is_allowed():
    """哨兵值 0 = 劫掠者寨子，合法的形态有且只有 [0]。"""
    assert _leader(target_levels=[RAIDER_TARGET]).target_levels == [0]


def test_raider_target_mixed_with_levels_rejected():
    """劫掠者寨子不分等级，与任何等级共存都无意义。"""
    with pytest.raises(ValidationError, match="不能再选其他等级"):
        _leader(target_levels=[RAIDER_TARGET, 6])


def test_raider_target_duplicate_rejected():
    """[0, 0] 也走「不能与其他目标共存」这条——0 不是可重复的等级。"""
    with pytest.raises(ValidationError, match="不能再选其他等级"):
        _leader(target_levels=[RAIDER_TARGET, RAIDER_TARGET])


def test_collision_warning_reads_raider_target_in_chinese():
    """撞车告警里 0 要写成「劫掠者寨子」，不能把哨兵值原样摊给用户看。"""
    a = _leader(id="c1", name="甲", target_levels=[RAIDER_TARGET],
                fill_target_leaders=[])
    b = CharacterConfig(id="c2", name="乙", role=RoleEnum.EITHER,
                        target_levels=[RAIDER_TARGET], march_preset=2,
                        march_troop_types=["cavalry"],
                        fill_target_leaders=[FillLeader(instance="i1", name="甲")])
    warns = find_level_collisions(_root(a, b).zhaiduo.instances)
    assert len(warns) == 1
    assert "劫掠者寨子" in warns[0] and "[0]" not in warns[0]


# ---- 多预设（2026-10-09）----

def test_march_presets_new_field_kept_in_order():
    c = _leader(march_presets=[{"preset": 3, "troops": ["archer"]},
                               {"preset": 1, "troops": ["infantry", "cavalry"]}])
    assert [p.preset for p in c.march_presets] == [3, 1]      # 顺序就是优先级
    assert c.march_presets[1].troops == ["infantry", "cavalry"]


def test_legacy_fields_migrate_into_one_preset():
    """老 config.yaml（只写 march_preset + march_troop_types）不改也能读。"""
    c = _leader()
    assert len(c.march_presets) == 1
    assert c.march_presets[0].preset == 1
    assert c.march_presets[0].troops == ["infantry"]


def test_march_presets_win_over_legacy_fields():
    """两者都写时以新字段为准，旧字段不参与。"""
    c = _leader(march_presets=[{"preset": 4, "troops": ["cavalry"]}],
                march_preset=2, march_troop_types=["archer"])
    assert len(c.march_presets) == 1
    assert c.march_presets[0].preset == 4


def test_neither_new_nor_legacy_field_raises():
    with pytest.raises(ValidationError, match="march_presets"):
        _leader(march_preset=None, march_troop_types=[])


def test_march_presets_reject_empty_troops():
    with pytest.raises(ValidationError, match="兵种"):
        _leader(march_presets=[{"preset": 1, "troops": []}])


def test_march_presets_reject_too_many():
    with pytest.raises(ValidationError, match="最多"):
        _leader(march_presets=[{"preset": 1, "troops": ["infantry"]},
                               {"preset": 2, "troops": ["infantry"]},
                               {"preset": 3, "troops": ["infantry"]},
                               {"preset": 4, "troops": ["infantry"]}])


def test_march_presets_reject_duplicate_slot():
    """同一槽位出现两次：第二条永远轮不到，是配置错误不是回退。"""
    with pytest.raises(ValidationError, match="重复"):
        _leader(march_presets=[{"preset": 2, "troops": ["infantry"]},
                               {"preset": 2, "troops": ["cavalry"]}])


def test_march_presets_reject_out_of_range_slot():
    with pytest.raises(ValidationError):
        _leader(march_presets=[{"preset": 6, "troops": ["infantry"]}])


# ---- InstanceBase 抽取（2026-10-17）----

def test_instance_base_holds_shared_fields():
    """公共字段与校验在基类上，子类只管自己的角色列表。"""
    from rok_assistant.infra.config import InstanceBase
    base = InstanceBase(id="i1", mumu_index=0, name="模拟器0")
    assert base.mumu_index == 0
    assert base.adb_address == ""
    assert base.window_title_pattern == ""


def test_instance_base_rejects_neither_mumu_nor_adb():
    from rok_assistant.infra.config import InstanceBase
    with pytest.raises(ValidationError) as e:
        InstanceBase(id="i1")
    assert "mumu_index 或 adb_address 必须填一个" in str(e.value)


def test_instance_base_rejects_both_mumu_and_adb():
    from rok_assistant.infra.config import InstanceBase
    with pytest.raises(ValidationError) as e:
        InstanceBase(id="i1", mumu_index=0, adb_address="127.0.0.1:7555")
    assert "只能填一个" in str(e.value)


def test_instance_config_still_rejects_duplicate_character_names():
    """抽出基类后，子类那条「角色名不重复」必须还在。"""
    with pytest.raises(ValidationError) as e:
        InstanceConfig(id="i1", mumu_index=0,
                       characters=[_leader(), _leader(id="c9")])
    assert "duplicate character names" in str(e.value)


def test_instance_config_is_an_instance_base():
    from rok_assistant.infra.config import InstanceBase
    assert issubclass(InstanceConfig, InstanceBase)


# ---- 宝石模式的角色与实例（2026-10-17）----

def test_gem_character_has_no_role_or_march_fields():
    """宝石模式没有分工、没有预设槽：这些字段不该存在。

    用 `hasattr` 负断言而不是 `getattr` + 比较 None：pydantic v2 的
    `__getattr__` 对未知字段抛 AttributeError，所以 `hasattr` 为 False
    就证明「不是 None，是没有」。
    """
    from rok_assistant.infra.config import GemCharacterConfig
    c = GemCharacterConfig(id="g1", name="宝石号")
    for field in ("role", "target_levels", "march_presets",
                  "march_preset", "march_troop_types", "fill_target_leaders"):
        assert not hasattr(c, field), f"GemCharacterConfig 不该有 {field}"


def test_gem_instance_requires_exactly_one_character():
    from rok_assistant.infra.config import GemInstanceConfig
    with pytest.raises(ValidationError) as e:
        GemInstanceConfig(id="mumu0", mumu_index=0, characters=[])
    assert "恰好 1 个角色" in str(e.value)

    with pytest.raises(ValidationError) as e:
        GemInstanceConfig(id="mumu0", mumu_index=0, characters=[
            {"id": "g1", "name": "A"}, {"id": "g2", "name": "B"}])
    assert "恰好 1 个角色" in str(e.value)


def test_gem_instance_inherits_mumu_adb_exclusivity():
    from rok_assistant.infra.config import GemInstanceConfig
    with pytest.raises(ValidationError):
        GemInstanceConfig(id="mumu0", mumu_index=0,
                          adb_address="127.0.0.1:7555",
                          characters=[{"id": "g1", "name": "A"}])


def test_gem_instance_accepts_one_character():
    from rok_assistant.infra.config import GemInstanceConfig
    inst = GemInstanceConfig(id="mumu0", name="宝石号", mumu_index=0,
                             characters=[{"id": "g1", "name": "宝石号"}])
    assert inst.characters[0].name == "宝石号"


# ---- GemConfig（2026-10-17）----

def _gem_root(**kw) -> RootConfig:
    gem = {"instances": [{"id": "mumu0", "mumu_index": 0,
                          "characters": [{"id": "g1", "name": "宝石号"}]}]}
    gem.update(kw)
    return RootConfig(zhaiduo={"instances": [InstanceConfig(
        id="i1", mumu_index=1, characters=[_leader()])]}, gem=gem)


def test_gem_config_defaults():
    from rok_assistant.infra.config import GemConfig
    g = GemConfig()
    assert g.queue_limit == 5
    assert g.max_rounds == 10
    assert g.scan_rings == 3
    assert g.scan_drag_px == 800
    assert g.scan_drag_ms == 500
    assert g.idle_wait_min == 20.0
    assert g.idle_wait_max == 30.0
    assert g.instances == []


def test_gem_config_rejects_inverted_wait_window():
    from rok_assistant.infra.config import GemConfig
    with pytest.raises(ValidationError) as e:
        GemConfig(idle_wait_min=30.0, idle_wait_max=20.0)
    assert "idle_wait_max" in str(e.value)


def test_gem_config_rejects_duplicate_instance_ids():
    from rok_assistant.infra.config import GemConfig
    one = {"id": "mumu0", "mumu_index": 0,
           "characters": [{"id": "g1", "name": "A"}]}
    two = {"id": "mumu0", "mumu_index": 1,
           "characters": [{"id": "g2", "name": "B"}]}
    with pytest.raises(ValidationError) as e:
        GemConfig(instances=[one, two])
    assert "gem 实例 id 重复" in str(e.value)


def test_gem_config_rejects_duplicate_character_ids():
    from rok_assistant.infra.config import GemConfig
    one = {"id": "mumu0", "mumu_index": 0,
           "characters": [{"id": "g1", "name": "A"}]}
    two = {"id": "mumu1", "mumu_index": 1,
           "characters": [{"id": "g1", "name": "B"}]}
    with pytest.raises(ValidationError) as e:
        GemConfig(instances=[one, two])
    assert "gem 角色 id 重复" in str(e.value)


def test_gem_config_queue_limit_bounds():
    from rok_assistant.infra.config import GemConfig
    assert GemConfig(queue_limit=7).queue_limit == 7
    with pytest.raises(ValidationError):
        GemConfig(queue_limit=0)
    with pytest.raises(ValidationError):
        GemConfig(queue_limit=8)


def test_root_config_instances_for_returns_gem_instances():
    root = _gem_root()
    insts = root.instances_for(AppMode.GEM)
    assert [i.id for i in insts] == ["mumu0"]
    assert insts[0].characters[0].name == "宝石号"
    # 两个模式各自独立：寨子段还是那一台
    assert [i.id for i in root.instances_for(AppMode.ZHAIDUO)] == ["i1"]


def test_root_config_gem_defaults_to_empty():
    root = RootConfig(zhaiduo={"instances": [InstanceConfig(
        id="i1", mumu_index=0, characters=[_leader()])]})
    assert root.instances_for(AppMode.GEM) == []


def test_gem_section_does_not_require_leader_role():
    """宝石模式没有 role 概念，套「至少一个 leader」会让它当场加载失败。"""
    root = _gem_root()
    assert root.gem.instances  # 没抛异常就是通过


# ---- 答题模式配置（2026-10-24）----

def _quiz_root(**quiz) -> RootConfig:
    """最小可加载配置：zhaiduo 段是陪跑的（RootConfig.zhaiduo 必填）。"""
    return RootConfig(
        zhaiduo={"instances": [_leader_inst()]},
        quiz={"instances": [{"id": "mumu0", "mumu_index": 0,
                             "characters": [{"id": "q0", "name": "答题号"}]}],
              **quiz})


def test_quiz_config_defaults():
    """默认值就是 spec §5 那张表：改默认值等于改行为，必须在这里留痕。"""
    cfg = QuizConfig()
    assert cfg.instances == []
    assert cfg.max_rounds == 3
    assert cfg.fuzzy_threshold == 0.72
    assert cfg.verify_delay == 1.2
    assert cfg.min_green_ratio == 0.55
    assert cfg.round_cooldown_min == 10.0
    assert cfg.parse_retries == 2
    assert cfg.auto_click is True
    assert cfg.entry_taps == []              # 空 = 只靠屏幕文字找入口
    assert cfg.llm.enabled is False          # 默认不发网络请求
    assert cfg.llm.timeout_s == 8.0


def test_quiz_llm_api_key_defaults_empty():
    """不填 Key 也能跑：题库外的题降级为随机。"""
    assert QuizLLMConfig().api_key == ""


def test_quiz_config_is_not_mode_config():
    """QuizConfig **不能**继承 ModeConfig：那是寨多多专属的 min_length=1 +
    leader/member 交叉校验，套到答题上会当场加载失败。"""
    assert not issubclass(QuizConfig, ModeConfig)
    assert _quiz_root().quiz.instances[0].id == "mumu0"


def test_quiz_instance_requires_exactly_one_character():
    with pytest.raises(ValidationError):
        QuizInstanceConfig(id="mumu0", mumu_index=0, characters=[])
    with pytest.raises(ValidationError):
        QuizInstanceConfig(id="mumu0", mumu_index=0, characters=[
            NoRoleCharacterConfig(id="a", name="甲"),
            NoRoleCharacterConfig(id="b", name="乙")])


def test_quiz_instance_keeps_mumu_adb_exclusive_check():
    """共用 InstanceBase 的校验：mumu_index 与 adb_address 必须二选一。"""
    with pytest.raises(ValidationError):
        QuizInstanceConfig(id="mumu0", mumu_index=0, adb_address="127.0.0.1:7555",
                           characters=[NoRoleCharacterConfig(id="q0", name="答题号")])
    with pytest.raises(ValidationError):
        QuizInstanceConfig(id="mumu0",
                           characters=[NoRoleCharacterConfig(id="q0", name="答题号")])


def test_quiz_rejects_duplicate_ids():
    dup_inst = {"instances": [
        {"id": "mumu0", "mumu_index": 0, "characters": [{"id": "a", "name": "甲"}]},
        {"id": "mumu0", "mumu_index": 1, "characters": [{"id": "b", "name": "乙"}]},
    ]}
    with pytest.raises(ValidationError):
        _quiz_root(**dup_inst)
    dup_char = {"instances": [
        {"id": "mumu0", "mumu_index": 0, "characters": [{"id": "a", "name": "甲"}]},
        {"id": "mumu1", "mumu_index": 1, "characters": [{"id": "a", "name": "乙"}]},
    ]}
    with pytest.raises(ValidationError):
        _quiz_root(**dup_char)


def test_gem_aliases_are_the_same_class_objects():
    """改名不退化成两套定义：别名必须**恒等**（pydantic 报错文案里的类名会变，
    这是可接受的代价；两套重复定义会慢慢漂移）。"""
    assert GemCharacterConfig is NoRoleCharacterConfig
    assert GemInstanceConfig is NoRoleInstanceConfig
    assert QuizInstanceConfig is NoRoleInstanceConfig
