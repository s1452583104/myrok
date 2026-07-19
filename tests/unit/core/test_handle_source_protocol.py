import numpy as np
from rok_assistant.core.handle_source import HandleSource

def test_protocol_is_runtime_checkable():
    class Fake:
        def capture(self): return np.zeros((10, 10, 3), dtype=np.uint8)
        def click(self, x, y): pass
        def is_alive(self): return True
    f = Fake()
    assert isinstance(f, HandleSource)
