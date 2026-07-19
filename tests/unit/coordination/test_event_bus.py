from rok_assistant.coordination.event_bus import EventBus

def test_subscribe_and_publish():
    bus = EventBus()
    received = []
    bus.subscribe("rally_launched", lambda payload: received.append(payload))
    bus.publish("rally_launched", {"rally_id": "r1"})
    assert received == [{"rally_id": "r1"}]

def test_multiple_subscribers():
    bus = EventBus()
    a, b = [], []
    bus.subscribe("e", lambda p: a.append(p))
    bus.subscribe("e", lambda p: b.append(p))
    bus.publish("e", {"x": 1})
    assert a == [{"x": 1}]
    assert b == [{"x": 1}]

def test_unsubscribe():
    bus = EventBus()
    received = []
    handler = lambda p: received.append(p)
    bus.subscribe("e", handler)
    bus.unsubscribe("e", handler)
    bus.publish("e", {"x": 1})
    assert received == []

def test_publish_with_no_subscribers_is_noop():
    bus = EventBus()
    bus.publish("nothing", {})  # should not raise
