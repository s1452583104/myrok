from __future__ import annotations
from typing import Callable, Union
from dataclasses import dataclass, field

@dataclass
class State:
    name: str

@dataclass
class Transition:
    from_state: str
    to_state: str
    action: Union[str, Callable]
    guard: Callable | None = None

class StateMachine:
    def __init__(self, initial: str):
        self._transitions: list[Transition] = []
        self.current = initial
        self.history: list[str] = [initial]
        self._ctx: dict = {}
        self._setup()

    def _setup(self) -> None:
        raise NotImplementedError

    def add_transition(self, from_state: str, to_state: str,
                       action: Union[str, Callable], guard: Callable | None = None) -> None:
        self._transitions.append(Transition(from_state, to_state, action, guard))

    def step(self, context: dict | None = None) -> None:
        if context is None:
            context = self._ctx
        else:
            self._ctx = context
        for t in self._transitions:
            if t.from_state != self.current:
                continue
            if t.guard and not t.guard(context):
                continue
            if callable(t.action):
                t.action(context)
            # else: action is a string label, nothing to invoke
            self.current = t.to_state
            self.history.append(self.current)
            return
        # No transition matched - stay in current state
