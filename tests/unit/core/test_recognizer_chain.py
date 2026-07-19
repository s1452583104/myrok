import numpy as np
from rok_assistant.core.recognizer import RecognizerChain, RecognizeResult, BBox, Recognizer

class StubRec(Recognizer):
    def __init__(self, name, matched, conf=0.9):
        self.name = name; self._m = matched; self._c = conf
    def recognize(self, screenshot):
        return RecognizeResult(matched=self._m, bbox=BBox(0,0,10,10) if self._m else None,
                               confidence=self._c, recognizer_id=self.name)

def test_chain_returns_first_match():
    chain = RecognizerChain([StubRec("a", False, 0.3), StubRec("b", True, 0.95)])
    r = chain.recognize(np.zeros((10,10,3), dtype=np.uint8))
    assert r.recognizer_id == "b"
    assert r.matched

def test_chain_falls_through_when_low_confidence():
    chain = RecognizerChain([StubRec("a", True, 0.3), StubRec("b", True, 0.9)],
                            threshold=0.5)
    r = chain.recognize(np.zeros((10,10,3), dtype=np.uint8))
    assert r.recognizer_id == "b"

def test_chain_no_match():
    chain = RecognizerChain([StubRec("a", False), StubRec("b", False)])
    r = chain.recognize(np.zeros((10,10,3), dtype=np.uint8))
    assert not r.matched
