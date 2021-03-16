
import bisect
class FloorDict:
    def __init__(self, init=None):
        super().__init__()
        self._dict = {}
        self._keys = []
        if init is not None:
            self._dict.update(init)
            self._keys = sorted(self._dict.keys())
    
    def __getitem__(self,key):
        if len(self._dict) == 0:
            return None
        if key in self._dict:
            return self._dict[key]
        else:
            pos = bisect.bisect_right(self._keys, key)
            return self._dict[self._keys[max(0,pos - 1)]]
    
    def __setitem__(self,key,value):
        if key not in self._dict:
            bisect.insort_right(self._keys, key)
        self._dict[key] = value
    
    def __contains__(self, key):
        return len(self._dict) > 0
    
    def __delitem__(self, key):
        del self._dict[key]
        self._keys.popitem(key)
    
    def __len__(self):
        return len(self._dict)
    
    def __repr__(self):
        return repr(self._dict)