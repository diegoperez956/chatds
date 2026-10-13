"""KB4 reader (reference): seek+read only through a one-sector buffer, exactly the read pattern of
clean/plumbing/kb4.c, so `sector_reads` agree between the two. Layout: FORMAT-KB4.md.

Errors: KB4Error.kind is 'io' (a read failed) or 'corrupt' (the bytes contradict the format)."""
import struct

SECTOR = 512
CAND_MAX = 4
FZ_NOFF = 16
MAX_SPAN = 4096
KEY_MAX = 63
HDR = 64

# relation codes of a field (record) / bit index in the cand masks
REL = {"definition": 0, "date_range": 1, "birth_date": 2, "birth_place": 3, "death_date": 4, "death_place": 5,
       "location": 6, "surname": 7, "capital": 8, "occupation": 9, "quantity": 10,
       "creator": 11, "height": 12, "length": 13}
REL_NAME = {v: k for k, v in REL.items()}
# canonical campaign vocabulary relation for each stored field
VOCAB = {"definition": "definition", "date_range": "date_range", "birth_date": "birth", "birth_place": "birth", "death_date": "death",
         "death_place": "death", "location": "location", "surname": "surname", "capital": "capital", "occupation": "occupation",
         "quantity": "quantity", "creator": "creator", "height": "quantity", "length": "quantity"}
ETYPE = {"other": 0, "person": 1, "event": 2, "place": 3, "country": 4}
ETYPE_NAME = {v: k for k, v in ETYPE.items()}
KIND = {"title": 0, "redirect": 1, "paren_base": 2, "derived": 3}
KIND_NAME = {v: k for k, v in KIND.items()}
PROV = {"none": 0, "title": 1, "infobox": 2, "lead_text": 3, "lead_sentence": 4, "lead_reverse": 5, "lead_bold": 6, "prose_sentence": 7}
PROV_NAME = {v: k for k, v in PROV.items()}


class KB4Error(Exception):
    def __init__(self, kind, msg=""):
        super().__init__("%s: %s" % (kind, msg))
        self.kind = kind


def fnv1a(b):
    h = 2166136261
    for c in b:
        h = ((h ^ c) * 16777619) & 0xFFFFFFFF
    return h


def del_eq(a, i, b, j):
    return (a[:i] + a[i + 1:]) == (b[:j] + b[j + 1:])


def share_variant(a, b):
    """a and b agree after deleting at most one char from each (same relation kb.c checks)."""
    return any(a[:i] + a[i + 1:] == b[:j] + b[j + 1:] for i in range(len(a) + 1) for j in range(len(b) + 1))


class Cand:
    __slots__ = ("key", "recoff", "kind", "prom", "etype", "pmask", "mmask")

    def __init__(self, key, recoff, kind, prom, etype, pmask, mmask):
        self.key, self.recoff, self.kind, self.prom, self.etype, self.pmask, self.mmask = key, recoff, kind, prom, etype, pmask, mmask

    def __repr__(self):
        return "Cand(%s,%d,%s,prom=%d,%s,p=%x,m=%x)" % (self.key, self.recoff, KIND_NAME.get(self.kind), self.prom, ETYPE_NAME.get(self.etype), self.pmask, self.mmask)


class KB4:
    def __init__(self, path, fault_after=None):
        self.f = open(path, "rb")
        self.fault_after = fault_after  # tests: raise an io error on the Nth sector read
        self.sector, self.sector_reads, self.lookups = None, 0, 0
        self.buf = b""
        self.f.seek(0, 2)
        real = self.f.tell()
        self.f.seek(0)
        h = self.f.read(HDR)
        self.version = struct.unpack_from('<I', h, 4)[0] if len(h) >= HDR else 0
        if real < SECTOR or len(h) < HDR or h[:4] != b"KB4\0" or self.version not in (4, 41):
            raise KB4Error("corrupt", "header")
        self.fnb, self.fbt, self.fent, self.fwo = struct.unpack_from("<4I", h, 36)
        self.fzmin = struct.unpack_from("<I", h, 60)[0] or 5  # shortest word in the delete index (0 = KB3-style 5)
        if not 3 <= self.fzmin <= 8:
            raise KB4Error("corrupt", "fuzzy min word")
        (self.nb, self.nk, self.nrec, self.bt, self.ko, self.ro, self.size) = struct.unpack_from("<IIIIIII", h, 8)
        pow2 = lambda x: x and not x & (x - 1)
        if real != self.size or not pow2(self.nb) or not pow2(self.fnb):
            raise KB4Error("corrupt", "size or bucket count")
        for o in (self.bt, self.ko, self.ro, self.fbt, self.fent, self.fwo):
            if o >= self.size:
                raise KB4Error("corrupt", "area offset")
        if not SECTOR <= self.bt < self.ko < self.ro < self.fwo < self.fbt < self.fent < self.size or any(o % SECTOR for o in (self.bt, self.ko, self.ro, self.fwo, self.fbt, self.fent)):
            raise KB4Error('corrupt', 'area order/alignment')
        if (self.ko - self.bt) // 4 <= self.nb or (self.fent - self.fbt) // 4 <= self.fnb:
            raise KB4Error("corrupt", "bucket table")

    def close(self):
        if hasattr(self, '_entres_index'):
            self._entres_index.close()
            del self._entres_index
        self.f.close()

    # one-sector buffer: same behavior as kb4.c rd()
    def _fill(self, s):
        if self.fault_after is not None and self.sector_reads >= self.fault_after:
            self.sector = None
            raise KB4Error("io", "injected")
        n = min(SECTOR, self.size - s * SECTOR)
        self.f.seek(s * SECTOR)
        b = self.f.read(n)
        if len(b) != n:
            self.sector = None
            raise KB4Error("io", "short read")
        self.buf, self.sector = b, s
        self.sector_reads += 1

    def rd(self, off, n):
        if off > self.size or n > self.size - off:
            raise KB4Error("corrupt", "read out of range")
        out = bytearray()
        while n:
            s, at = off // SECTOR, off % SECTOR
            k = min(SECTOR - at, n)
            if s != self.sector:
                self._fill(s)
            out += self.buf[at:at + k]
            off += k
            n -= k
        return bytes(out)

    def bucket(self, tab, b):
        a, e = struct.unpack("<2I", self.rd(tab + 4 * b, 8))
        if e < a:
            raise KB4Error("corrupt", "bucket order")
        return a, e

    def lookup(self, key):
        """key: normalized ASCII str. -> list[Cand] (<= CAND_MAX), [] on miss."""
        self.lookups += 1
        kb = key.encode("latin-1")
        if not kb or len(kb) > KEY_MAX:
            return []
        h = fnv1a(kb)
        a, e = self.bucket(self.bt, h & (self.nb - 1))
        if e > self.ro - self.ko or e - a > MAX_SPAN * (6 + KEY_MAX + 11 * CAND_MAX):
            raise KB4Error("corrupt", "bucket span")
        i = a
        while i < e:
            hh, kl, nc = struct.unpack("<IBB", self.rd(self.ko + i, 6))
            if kl > KEY_MAX or i + 6 + kl + 11 * nc > e or nc > CAND_MAX or nc == 0:
                raise KB4Error("corrupt", "ncand")
            if hh == h and kl == len(kb):
                k = self.rd(self.ko + i + 6, kl)
                if k == kb:
                    raw = self.rd(self.ko + i + 6 + kl, 11 * nc)
                    out = []
                    for c in range(nc):
                        ro, kind, prom, et, pm, mm = struct.unpack_from("<IBBBHH", raw, 11 * c)
                        if ro >= self.size - self.ro or kind > 3 or et > 4:
                            raise KB4Error("corrupt", "record offset")
                        out.append(Cand(key, ro, kind, prom, et, pm, mm))
                    return out
            i += 6 + kl + 11 * nc
        return []

    def record(self, recoff):
        """-> dict(eid, etype, prom, title, definition, fields {name: (value|None, prov, missing)})"""
        if recoff < 0 or recoff + 2 > self.fwo - self.ro:
            raise KB4Error('corrupt', 'record offset')
        (n,) = struct.unpack("<H", self.rd(self.ro + recoff, 2))
        if n < 10 or n > 510 or recoff + 2 + n > self.fwo - self.ro:
            raise KB4Error("corrupt", "record length")
        b = self.rd(self.ro + recoff + 2, n)
        eid, et, prom, tl = struct.unpack_from("<IBBB", b, 0)
        p = 7
        if tl > 63 or p + tl + 1 > n:
            raise KB4Error("corrupt", "record title")
        title = b[p:p + tl]; p += tl
        dl = b[p]; p += 1
        if dl > 111 or p + dl + 1 > n:
            raise KB4Error("corrupt", "record definition")
        definition = b[p:p + dl]; p += dl
        nf = b[p]; p += 1
        if nf > (14 if self.version == 41 else 12):
            raise KB4Error("corrupt", "record field count")
        fields, field_sources = {}, {}
        for _ in range(nf):
            if p + 3 > n:
                raise KB4Error("corrupt", "record field")
            rel, fl, vl = b[p], b[p + 1], b[p + 2]; p += 3
            if p + vl > n or rel not in REL_NAME or rel == 0 or vl > 63 or (self.version == 4 and rel > 10) or fl > (31 if self.version == 41 else 15):
                raise KB4Error("corrupt", "record field")
            fields[REL_NAME[rel]] = (b[p:p + vl] if not fl & 1 else None, (fl >> 1) & 7, bool(fl & 1))
            p += vl
            if self.version == 41:
                if p + 4 > n:
                    raise KB4Error('corrupt', 'field source')
                sid, end_sid = struct.unpack_from('<HH', b, p)
                if (250 <= sid < 65532) or (250 <= end_sid < 65532):
                    raise KB4Error('corrupt', 'field source ordinal')
                field_sources[REL_NAME[rel]] = dict(sid=sid, end_sid=end_sid, conflict=bool(fl & 16))
                p += 4
        try:
            title, definition = title.decode("ascii"), definition.decode("ascii")
            fields = {k: ((v[0].decode("ascii") if v[0] is not None else None), v[1], v[2]) for k, v in fields.items()}
        except UnicodeDecodeError:
            raise KB4Error("corrupt", "record not ascii")
        fields = dict(definition=(definition, PROV["lead_sentence"], False), **fields)
        return dict(eid=eid, etype=et, prom=prom, title=title, definition=definition, fields=fields, field_sources=field_sources)

    def fuzzy(self, q):
        """(known, words): known = q itself is an indexed word; words = indexed words within one edit/transposition of q,
        most frequent first (<= CAND_MAX). Mirrors cds_kb4_fuzzy."""
        known = False
        nq = len(q)
        if nq > KEY_MAX:
            return False, []
        offs = []
        for d in range(nq, -1, -1):
            if 0 < d < nq and q[d] == q[d - 1]:
                continue
            v = (q[:d] + q[d + 1:]).encode("latin-1") if d < nq else q.encode("latin-1")
            h = fnv1a(v)
            a, e = self.bucket(self.fbt, h & (self.fnb - 1))
            if e > self.size - self.fent or (e - a) % 8 or e - a > 8 * MAX_SPAN:
                raise KB4Error("corrupt", "fuzzy span")
            i = a
            while i + 8 <= e:
                eh, wo = struct.unpack("<II", self.rd(self.fent + i, 8))
                i += 8
                if eh != h:
                    continue
                if wo in offs:
                    continue
                at = len([o for o in offs if o < wo])
                if at == FZ_NOFF:
                    continue
                offs.insert(at, wo)
                del offs[FZ_NOFF:]
        out = []
        for wo in offs:
            if len(out) == CAND_MAX and known:
                break
            if wo > self.size - self.fwo:
                return known, out
            n = self.rd(self.fwo + wo, 1)[0]
            w = self.rd(self.fwo + wo + 1, n)
            if n > KEY_MAX:
                continue
            w = w.decode("latin-1")  # corrupt files may hold any byte; keep them as bytes
            if w == q:
                known = True
                continue
            if share_variant(w, q) and len(out) < CAND_MAX:
                out.append(w)
        return known, out
