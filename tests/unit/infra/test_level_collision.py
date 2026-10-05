from rok_assistant.infra.config import RootConfig, find_level_collisions


def _levels(v) -> list:
    """允许传单个数（旧用法）或列表（多选）。"""
    return [v] if isinstance(v, int) else list(v)


def _cfg(level_a, level_b, fill_ab=True, fill_ba=True):
    a_targets = [{"instance": "i1", "name": "B"}] if fill_ab else []
    b_targets = [{"instance": "i0", "name": "A"}] if fill_ba else []
    # 现有模型约束：member/either 必须配 fill_target_leaders，且 leader 不能配。
    # 所以「不填兵」的一侧只能是 leader。这与 brief 里两侧都写 either 的意图等价
    # （leader 同样是开车角色，会被 find_level_collisions 计入），只是让 fixture
    # 能通过 RootConfig 校验 —— brief 的原始 fixture 在关闭某一方向填兵时会构造出
    # 非法的 either（空 fill_target_leaders），无法 model_validate。
    a_role = "either" if fill_ab else "leader"
    b_role = "either" if fill_ba else "leader"
    return RootConfig.model_validate({
        "instances": [
            {"id": "i0", "mumu_index": 0, "characters": [
                {"id": "ca", "name": "A", "role": a_role,
                 "target_levels": _levels(level_a), "march_preset": 1,
                 "march_troop_types": ["infantry"],
                 "fill_target_leaders": a_targets}]},
            {"id": "i1", "mumu_index": 1, "characters": [
                {"id": "cb", "name": "B", "role": b_role,
                 "target_levels": _levels(level_b), "march_preset": 1,
                 "march_troop_types": ["cavalry"],
                 "fill_target_leaders": b_targets}]},
        ]})


def test_same_level_mutual_fill_warns():
    msgs = find_level_collisions(_cfg(7, 7))
    assert len(msgs) == 1
    assert "7" in msgs[0]
    assert "建议错开等级" in msgs[0]


def test_different_level_is_silent():
    """两号配不同等级 → 不会搜到同一寨子 → 无告警。
    这是删除 _FOREIGN_RALLY_WINDOW 的前提。"""
    assert find_level_collisions(_cfg(7, 6)) == []


def test_partial_overlap_warns():
    """多选后不再比「相等」：只要两个列表有共同等级就会撞车。
    这里 A=[7,6]、B=[6,5] 都不相等，但 6 级会撞。"""
    msgs = find_level_collisions(_cfg([7, 6], [6, 5]))
    assert len(msgs) == 1
    assert "6 级" in msgs[0]
    assert "7 级" not in msgs[0]   # 只报真正重叠的等级


def test_no_overlap_is_silent():
    """列表都非单元素但完全不重叠 → 不会撞车。"""
    assert find_level_collisions(_cfg([7, 6], [5, 4])) == []


def test_same_level_one_direction_still_warns():
    """A 填 B、B 不填 A：同样会撞车，只查「互为」会漏。"""
    msgs = find_level_collisions(_cfg(7, 7, fill_ba=False))
    assert len(msgs) == 1
    # 单方向时关系并不互反，文案不能声称「互为」
    assert "互为" not in msgs[0]


def test_same_level_no_fill_relation_is_silent():
    """两号同等级但互不填兵（不同联盟，各自为战）→ 不告警。"""
    assert find_level_collisions(
        _cfg(7, 7, fill_ab=False, fill_ba=False)) == []


def test_pure_member_does_not_participate():
    """纯 member 不开车，不参与撞车判定。"""
    cfg = RootConfig.model_validate({
        "instances": [
            {"id": "i0", "mumu_index": 0, "characters": [
                {"id": "ca", "name": "A", "role": "leader",
                 "target_levels": [7], "march_preset": 1,
                 "march_troop_types": ["infantry"]}]},
            {"id": "i1", "mumu_index": 1, "characters": [
                {"id": "cb", "name": "B", "role": "member",
                 "target_levels": [7], "march_preset": 1,
                 "march_troop_types": ["cavalry"],
                 "fill_target_leaders": [{"instance": "i0", "name": "A"}]}]},
        ]})
    assert find_level_collisions(cfg) == []
