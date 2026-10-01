from rok_assistant.infra.config import RootConfig, find_level_collisions


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
                 "target_level": level_a, "march_preset": 1,
                 "march_troop_types": ["infantry"],
                 "fill_target_leaders": a_targets}]},
            {"id": "i1", "mumu_index": 1, "characters": [
                {"id": "cb", "name": "B", "role": b_role,
                 "target_level": level_b, "march_preset": 1,
                 "march_troop_types": ["cavalry"],
                 "fill_target_leaders": b_targets}]},
        ]})


def test_same_level_mutual_fill_warns():
    msgs = find_level_collisions(_cfg(7, 7))
    assert len(msgs) == 1
    assert "7" in msgs[0]
    assert "不同等级" in msgs[0]


def test_different_level_is_silent():
    """两号配不同等级 → 不会搜到同一寨子 → 无告警。
    这是删除 _FOREIGN_RALLY_WINDOW 的前提。"""
    assert find_level_collisions(_cfg(7, 6)) == []


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
                 "target_level": 7, "march_preset": 1,
                 "march_troop_types": ["infantry"]}]},
            {"id": "i1", "mumu_index": 1, "characters": [
                {"id": "cb", "name": "B", "role": "member",
                 "target_level": 7, "march_preset": 1,
                 "march_troop_types": ["cavalry"],
                 "fill_target_leaders": [{"instance": "i0", "name": "A"}]}]},
        ]})
    assert find_level_collisions(cfg) == []
