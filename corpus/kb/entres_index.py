"""ER1 source-only alias sidecar. Sector-cached, no whole-index runtime load."""
import struct
from kb4 import KB4, KB4Error, Cand, fnv1a, MAX_SPAN, KEY_MAX

MAX_BYTES = 64 * 1024 * 1024
MAX_KEYS = 1000000

class AliasCand(Cand):
    __slots__ = ('pop', 'weak')

class EntIndex(KB4):
    def __init__(self, path, base):
        self.f = open(path, 'rb')
        self.fault_after = None
        self.sector, self.sector_reads, self.lookups, self.buf = None, 0, 0, b''
        try:
            self.f.seek(0, 2)
            real = self.f.tell()
            self.f.seek(0)
            h = self.f.read(512)
            if len(h) != 512 or h[:4] != b'ER1\0':
                raise KB4Error('corrupt', 'entres header')
            ver, self.size, self.nb, self.nk, self.bt, self.ko, bs, bh = struct.unpack_from('<8I', h, 4)
            base.f.seek(0)
            expected = fnv1a(base.f.read(64))
            if ver != 1 or real != self.size or self.size > MAX_BYTES or self.nk > MAX_KEYS or bs != base.size or bh != expected:
                raise KB4Error('corrupt', 'entres version/size/base')
            if not self.nb or self.nb & (self.nb - 1) or self.nb > MAX_KEYS or self.bt != 512 or self.ko % 512 or self.ko >= self.size or self.ko - self.bt < 4 * (self.nb + 1):
                raise KB4Error('corrupt', 'entres layout')
            self.record_bytes = base.fwo - base.ro
        except Exception:
            self.f.close()
            raise

    def lookup(self, key):
        self.lookups += 1
        b = key.encode('latin-1')
        if not b or len(b) > KEY_MAX:
            return []
        h = fnv1a(b)
        a, e = self.bucket(self.bt, h & (self.nb - 1))
        if e > self.size - self.ko or e - a > 4096:
            raise KB4Error('corrupt', 'entres bucket span')
        out = []
        while a < e:
            if e - a < 6:
                raise KB4Error('corrupt', 'entres entry')
            hh, kl, nc = struct.unpack('<IBB', self.rd(self.ko + a, 6))
            length = 6 + kl + 13 * nc
            if not 1 <= kl <= 63 or not 1 <= nc <= 4 or length > e - a:
                raise KB4Error('corrupt', 'entres entry')
            if hh == h and kl == len(b) and self.rd(self.ko + a + 6, kl) == b:
                raw = self.rd(self.ko + a + 6 + kl, 13 * nc)
                for i in range(nc):
                    ro, kind, prom, et, pm, mm, pop, weak = struct.unpack_from('<IBBBHHBB', raw, 13 * i)
                    if ro + 2 > self.record_bytes or kind > 3 or prom > 63 or et > 4 or pop > 63 or weak > 1 or (pm | mm) >> 14:
                        raise KB4Error('corrupt', 'entres candidate')
                    c = AliasCand(key, ro, kind, prom, et, pm, mm)
                    c.pop, c.weak = pop, weak
                    out.append(c)
                return out
            a += length
        return out
