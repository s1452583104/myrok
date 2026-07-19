import pytest
from rok_assistant.workers.state_machine import StateMachine, State, Transition

class Counter(StateMachine):
    def _setup(self):
        self.add_transition("start", "counting", "increment")
        self.add_transition("counting", "counting", "increment", guard=lambda ctx: ctx["n"] < 3)
        self.add_transition("counting", "done", "finish", guard=lambda ctx: ctx["n"] >= 3)

def test_initial_state():
    c = Counter(initial="start")
    assert c.current == "start"

def test_transition():
    c = Counter(initial="start")
    c.step({})
    assert c.current == "counting"

def test_guard_blocks_transition():
    c = Counter(initial="start")
    c.step({})
    c.step({"n": 10})  # would skip counting
    assert c.current == "done"

def test_history():
    c = Counter(initial="start")
    c.step({})
    c.step({"n": 1})
    c.step({"n": 2})
    c.step({"n": 3})
    assert c.history == ["start", "counting", "counting", "counting", "done"]
