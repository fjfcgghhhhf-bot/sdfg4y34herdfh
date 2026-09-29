"""Windows helper restoration check with a fake API; no screen changes."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
import grayscale

class Pipe:
    def __init__(self): self.messages=[]; self.polls=0
    def send(self,value): self.messages.append(value)
    def poll(self,*_): self.polls+=1; return self.polls>1
    def close(self): pass
class API:
    def __init__(self,fail=False): self.original=object(); self.changes=[]; self.closed=False; self.fail=fail
    def capture(self): return self.original
    def change(self,value):
        self.changes.append(value)
        if self.fail and len(self.changes)==1: raise RuntimeError('test failure')
    def close(self): self.closed=True
for fail in (False,True):
    api=API(fail); pipe=Pipe()
    with patch.object(grayscale,'ColourAPI',return_value=api): grayscale._grayscale_worker(pipe,60)
    assert len(api.changes)==2 and api.changes[-1] is api.original and api.closed
    assert pipe.messages[-1]==('finished',None)
print('PASS grayscale restores captured matrix after stop and partial failure')
