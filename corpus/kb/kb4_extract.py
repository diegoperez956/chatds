"""KB4 field extraction: wikitext -> {title-independent typed fields with provenance}.

Own implementation (brace matching, infobox params, date templates, lead patterns). Nothing here is shared with
campaign/eval. Values are ASCII. Dates are ISO-ish: YYYY, YYYY-MM or YYYY-MM-DD (leading '-' = BC).
A field is (relation_code, value, prov). Provenance kinds: see PROV."""
import html, re, unicodedata

from kb import ascii_only

PROV = {"title": 1, "infobox": 2, "lead_text": 3, "lead_sentence": 4, "lead_reverse": 5, "lead_bold": 6}
MONTHS = {m: i + 1 for i, m in enumerate("january february march april may june july august september october november december".split())}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_ISO = "\x01-?\\d{1,4}(?:-\\d\\d){0,2}\x02"          # expanded date template marker
_DATE_RE = re.compile(
    "(?P<iso>%s)|\\b(?P<d1>\\d{1,2})\\s+(?P<m1>%s)\\.?,?\\s+(?P<y1>\\d{3,4})(?:\\s*(?P<bc1>BC|BCE))?"
    "|\\b(?P<m2>%s)\\.?\\s+(?P<d2>\\d{1,2})(?:st|nd|rd|th)?,?\\s+(?P<y2>\\d{3,4})"
    "|\\b(?P<m3>%s)\\.?,?\\s+(?P<y3>\\d{3,4})|\\b(?P<y4>\\d{3,4})(?:\\s*(?P<bc4>BC|BCE)\\b)?" % (_ISO, _MON, _MON, _MON), re.I)

def _iso(y, m=0, d=0, bc=False):
    y, m, d = int(y), int(m or 0), int(d or 0)
    if y == 0 or not 0 <= m <= 12 or not 0 <= d <= 31 or (d and not m):
        return None
    s = ("-%04d" if bc else "%04d") % y
    if m:
        s += "-%02d" % m
    if d:
        s += "-%02d" % d
    return s

def scan_dates(t):
    """ordered list of ISO dates found in cleaned text (expanded templates first)."""
    out = []
    for m in _DATE_RE.finditer(t):
        g = m.groupdict()
        if m.group("iso"):
            out.append(m.group("iso").strip("\x01\x02"))
        elif g["y1"]:
            out.append(_iso(g["y1"], MONTHS[g["m1"].lower()[:3]], g["d1"], bool(g["bc1"])))
        elif g["y2"]:
            out.append(_iso(g["y2"], MONTHS[g["m2"].lower()[:3]], g["d2"]))
        elif g["y3"]:
            out.append(_iso(g["y3"], MONTHS[g["m3"].lower()[:3]]))
        else:
            out.append(_iso(g["y4"], 0, 0, bool(g["bc4"])))
    return [d for d in out if d]

# ---- brace-aware splitting ----
def find_template(text, name_re):
    """body of the first top-level {{name ...}} whose name matches name_re (string between the braces) or None."""
    m = re.search(r"\{\{\s*(?:%s)" % name_re, text, re.I)
    if not m:
        return None
    i = m.start()
    depth, j = 0, i
    while j < len(text) - 1:
        two = text[j:j + 2]
        if two == "{{":
            depth += 1; j += 2
        elif two == "}}":
            depth -= 1; j += 2
            if depth == 0:
                return text[i + 2:j - 2], text[:i] + text[j:]
        else:
            j += 1
    return text[i + 2:], text[:i]  # truncated page: use the open template as far as it goes

def split_top(s):
    parts, depth, cur, i = [], 0, [], 0
    while i < len(s):
        two = s[i:i + 2]
        if two in ("{{", "[["):
            depth += 1; cur.append(two); i += 2; continue
        if two in ("}}", "]]"):
            depth -= 1; cur.append(two); i += 2; continue
        if s[i] == "|" and depth == 0:
            parts.append("".join(cur)); cur = []
        else:
            cur.append(s[i])
        i += 1
    parts.append("".join(cur))
    return parts

def infobox_params(wt):
    """(infobox_name, {param: raw}) or (None, {})"""
    r = find_template(wt, r"infobox[ _]")
    if not r:
        return None, {}
    body = r[0]
    parts = split_top(body)
    name = re.sub(r"<!--.*?-->", "", parts[0], flags=re.S).strip()
    name = re.sub(r"^infobox[ _]", "", name, flags=re.I).strip().lower()
    prm = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            k = re.sub(r"[ _]+", "_", k.strip().lower())
            if k and k not in prm:
                prm[k] = v.strip()
    return name, prm

# ---- value cleaning ----
_DT = {"birth date": 1, "birth-date": 1, "birth date and age": 1, "birth date and age2": 0, "death date": 1, "death date and age": 1,
       "start date": 1, "start date and age": 1, "end date": 1, "dob": 1, "birth based on age as of date": 0,
       "start and end dates": 2, "start-end dates": 2, "end date and age": 1, "film date": 1, "date": 1, "bda": 1, "dda": 1,
       "birth year and age": 1, "death year and age": 1, "birth year": 1, "death year": 1}

def _expand_dates(t):
    """replace known date templates (innermost first) by \x01ISO\x02 markers."""
    def rep(m):
        parts = [p.strip() for p in m.group(1).split("|")]
        nm = parts[0].lower().strip()
        if nm not in _DT:
            return m.group(0)
        pos = [p for p in parts[1:] if re.fullmatch(r"-?\d{1,4}", p)]
        if nm == "birth date and age2":
            pos = pos[3:6]
        out = []
        for chunk in ([pos[:3], pos[3:6]] if _DT[nm] == 2 else [pos[:3]]):
            if chunk and chunk[0].lstrip("-").isdigit():
                iso = _iso(abs(int(chunk[0])), chunk[1] if len(chunk) > 1 else 0, chunk[2] if len(chunk) > 2 else 0, chunk[0].startswith("-"))
                if iso:
                    out.append("\x01%s\x02" % iso)
        return " ".join(out) if out else ""
    prev = None
    while prev != t:
        prev, t = t, re.sub(r"\{\{([^{}]*)\}\}", rep_if_date(rep), t)
    return t

def rep_if_date(rep):
    def f(m):
        nm = m.group(1).split("|")[0].strip().lower()
        return rep(m) if nm in _DT else m.group(0).replace("{{", "\x03").replace("}}", "\x04")  # park non-date templates
    return f

_LIST_TPL = re.compile(r"\x03\s*(?:hlist|flatlist|plainlist|unbulleted list|ubl|bulleted list|nowrap|nobold|small|smaller|plain list|collapsible list)\s*\|([^\x03\x04]*)\x04", re.I)

ISO3 = {c: n for cs, n in (
    ("USA", "United States"), ("GBR UK", "United Kingdom"), ("FRA", "France"), ("GER DEU", "Germany"), ("ITA", "Italy"), ("ESP", "Spain"),
    ("POR PRT", "Portugal"), ("NED NLD", "Netherlands"), ("BEL", "Belgium"), ("SUI CHE", "Switzerland"), ("AUT", "Austria"), ("SWE", "Sweden"),
    ("NOR", "Norway"), ("DEN DNK", "Denmark"), ("FIN", "Finland"), ("POL", "Poland"), ("CZE", "Czech Republic"), ("HUN", "Hungary"),
    ("ROU ROM", "Romania"), ("BUL BGR", "Bulgaria"), ("GRE GRC", "Greece"), ("TUR", "Turkey"), ("RUS", "Russia"), ("UKR", "Ukraine"),
    ("BLR", "Belarus"), ("CHN", "China"), ("JPN", "Japan"), ("KOR", "South Korea"), ("PRK", "North Korea"), ("IND", "India"), ("PAK", "Pakistan"),
    ("BAN BGD", "Bangladesh"), ("IDN INA", "Indonesia"), ("PHI PHL", "Philippines"), ("VNM VIE", "Vietnam"), ("THA", "Thailand"),
    ("MAS MYS", "Malaysia"), ("SIN SGP", "Singapore"), ("AUS", "Australia"), ("NZL", "New Zealand"), ("CAN", "Canada"), ("MEX", "Mexico"),
    ("BRA", "Brazil"), ("ARG", "Argentina"), ("CHI CHL", "Chile"), ("COL", "Colombia"), ("PER", "Peru"), ("VEN", "Venezuela"), ("EGY", "Egypt"),
    ("RSA ZAF", "South Africa"), ("NGA", "Nigeria"), ("KEN", "Kenya"), ("ETH", "Ethiopia"), ("MAR", "Morocco"), ("ALG DZA", "Algeria"),
    ("IRN", "Iran"), ("IRQ", "Iraq"), ("ISR", "Israel"), ("SAU KSA", "Saudi Arabia"), ("AFG", "Afghanistan"), ("IRL", "Ireland"),
    ("SCO", "Scotland"), ("ENG", "England"), ("WAL", "Wales"), ("CRO HRV", "Croatia"), ("SRB", "Serbia"), ("SVK", "Slovakia"),
    ("SVN", "Slovenia"), ("LTU", "Lithuania"), ("LVA", "Latvia"), ("EST", "Estonia"), ("ISL", "Iceland"), ("CUB", "Cuba"), ("JAM", "Jamaica")) for c in cs.split()}


def clean_value(v):
    """infobox/lead value -> plain ASCII text (dates stay as markers)."""
    v = re.sub(r"<!--.*?(?:-->|$)", "", v, flags=re.S)
    v = re.sub(r"<ref[^>/]*/>|<ref\b[^>]*>.*?</ref>", "", v, flags=re.S | re.I)
    v = re.sub(r"\{\{\s*([A-Z]{3})\s*\}\}", lambda m: ISO3.get(m.group(1), ""), v)  # {{PHL}} flag templates -> country name
    v = re.sub(r"\{\{\s*(?:flag|flagcountry)\s*\|\s*([^{}|]+?)\s*(?:\|[^{}]*)?\}\}", r"\1", v, flags=re.I)
    v = _expand_dates(v)
    for _ in range(4):  # unwrap list/format templates, then drop the rest
        v2 = _LIST_TPL.sub(lambda m: m.group(1).replace("|", ", "), v)
        if v2 == v:
            break
        v = v2
    v = re.sub(r"\x03[^\x03\x04]*\x04", "", v)
    v = v.replace("\x03", "").replace("\x04", "")
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    prev = None
    while prev != v:
        prev = v
        v = re.sub(r"\[\[(?:File|Image|Category):[^\]]*\]\]", "", v, flags=re.I)
        v = re.sub(r"\[\[[^\[\]|]*\|([^\[\]]*)\]\]", r"\1", v)
        v = re.sub(r"\[\[([^\[\]]*)\]\]", r"\1", v)
    v = re.sub(r"\[https?://[^\s\]]+\s*([^\]]*)\]", r"\1", v)
    v = re.sub(r"<br\s*/?>|</?li>|^\s*[*#]\s*|\n\s*[*#]\s*", ", ", v, flags=re.I | re.M)
    v = re.sub(r"<[^>]*>", "", v)
    v = html.unescape(v).replace("\xa0", " ")
    v = re.sub(r"'{2,}", "", v)
    keep = re.findall(r"\x01[^\x02]*\x02", v)
    v = ascii_only(v) if not keep else "".join(ascii_only(p) if "\x01" not in p and "\x02" not in p else p for p in re.split(r"(\x01[^\x02]*\x02)", v))
    v = re.sub(r"\s+", " ", v)
    v = re.sub(r"(?:,\s*){2,}", ", ", v)
    return v.strip(" ,;")

def plain(v):
    """clean_value with date markers shown as their ISO text (for names/places)."""
    return re.sub(r"\x01([^\x02]*)\x02", r"\1", clean_value(v))

def _trim(v, n):
    v = plain(v)
    if len(v) <= n:
        return v
    cut = v[:n + 1]
    i = max(cut.rfind(","), cut.rfind(" "))
    return cut[:i if i > 0 else n].rstrip(" ,;")

# ---- fields from an infobox ----
_EVENT_BOX = re.compile(r"conflict|war|battle|event|earthquake|disaster|election|treaty|protest|massacre|siege|attack|rebellion|"
                        r"revolution|accident|storm|hurricane|olympics|tournament|festival|crime|incident|operation|tropical|flood|eruption|"
                        r"coup|strike|riot|referendum|expedition|summit|concert|competition|race|season|launch|mission")
_PLACE_BOX = re.compile(r"settlement|city|town|commune|comune|location|county|district|village|municipality|river|mountain|island|"
                        r"lake|place|state|province|region|park|building|bridge|airport|station|castle|volcano|valley|desert|"
                        r"canal|dam|island|peninsula|sea|ocean|forest|university|school|stadium|museum|church|road")

def _first_param(prm, *names):
    for n in names:
        if prm.get(n, "").strip():
            return prm[n]
    return None

def date_field(raw):
    """raw infobox text -> 'a/b' range, 'a' single, or None."""
    t = clean_value(raw)
    t = re.sub(r"\(.*?\)", " ", t)  # age notes
    ds = _bc(t, scan_dates(t))
    if not ds:
        return None
    if len(ds) == 1:
        return ds[0]
    # first and last mention bound the span; ignore later "other dates" notes beyond the second
    a, b = ds[0], ds[1]
    return a if a == b else "%s/%s" % (a, b)

def _bc(t, ds):
    if re.search(r"\bBCE?\b", t) and not re.search(r"\bADC?E?\b", t):
        return [d if d.startswith("-") else "-" + d for d in ds]
    return ds

def point_date(raw):
    t = re.sub(r"\(.*?\)", " ", clean_value(raw))
    ds = _bc(t, scan_dates(t))
    return ds[0] if ds else None

def person_fields(prm):
    f = {}
    for key, rel in (("birth_date", "birth_date"), ("born", "birth_date"), ("death_date", "death_date"), ("died", "death_date")):
        raw = prm.get(key)
        if raw and rel not in f:
            d = point_date(raw)
            if d:
                f[rel] = (d, "infobox")
    for key, rel in (("birth_place", "birth_place"), ("death_place", "death_place")):
        raw = prm.get(key)
        if raw:
            v = _trim(raw, 60)
            if v and not re.search(r"\x01", v):
                f[rel] = (v, "infobox")
    raw = _first_param(prm, "occupation", "profession")
    if raw:
        v = _trim(raw, 60)
        if v:
            f["occupation"] = (v, "infobox")
    return f

def event_fields(prm):
    f = {}
    raw = _first_param(prm, "date", "dates", "start_date", "formed", "began", "start", "year", "duration", "time", "dated")
    end = _first_param(prm, "end_date", "dissipated", "ended", "end")
    if raw:
        if end and not prm.get("date") and not prm.get("dates"):
            raw = clean_value(raw) + " " + clean_value(end)
        d = date_field(raw)
        if d:
            f["date_range"] = (d, "infobox")
    raw = _first_param(prm, "place", "location", "venue", "site", "areas_affected", "affected", "area")
    if raw:
        v = re.sub(r"^[A-Za-z ]{3,25}:\s*,?\s*", "", _trim(raw, 60))
        if v:
            f["location"] = (v, "infobox")
    return f

def place_fields(prm):
    f = {}
    raw = _first_param(prm, "capital")
    if raw:
        v = _trim(raw, 40)
        if v and v.lower() not in ("none", "n/a", "yes"):
            f["capital"] = (v, "infobox")
    pieces = []
    for k in ("subdivision_name", "subdivision_name1", "country", "state", "region", "location", "department", "canton", "district_name", "province"):
        raw = prm.get(k)
        if raw:
            v = _trim(raw, 40)
            if v and v not in pieces and len(v) > 1 and not v.lower().startswith(("http", "[[file")):
                pieces.append(v)
        if len(pieces) == 2:
            break
    if pieces and not prm.get("capital"):  # a country has a capital, not a location
        f["location"] = (", ".join(pieces)[:60], "infobox")
    raw = _first_param(prm, "population_total", "population", "population_estimate", "pop", "population_census")
    if raw:
        t = re.sub(r"\(.*?\)", " ", clean_value(raw))
        m = re.search(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?![\d,])|(?<![\d.,])\d{3,}(?![\d,])", t)
        if m:
            f["quantity"] = (m.group(0).replace(",", ""), "infobox")
    return f

# ---- lead text ----
def lead_raw(wt):
    """first prose paragraph with parentheses kept; dates expanded; infobox/hatnotes/files gone."""
    t = wt
    while True:
        r = find_template(t, r"infobox[ _]") or find_template(t, r"taxobox|speciesbox|automatic taxobox")
        if not r:
            break
        t = r[1]
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"<ref[^>/]*/>|<ref\b[^>]*>.*?</ref>", "", t, flags=re.S | re.I)
    t = _expand_dates(t)
    prev = None
    while prev != t:
        prev, t = t, re.sub(r"\{\{[^{}]*\}\}", "", t)
    t = re.sub(r"\x03[^\x03\x04]*\x04", "", t)
    while re.search(r"\x03[^\x03\x04]*\x04", t):
        t = re.sub(r"\x03[^\x03\x04]*\x04", "", t)
    t = t.replace("\x03", "").replace("\x04", "")
    for line in t.split("\n"):
        line = line.strip()
        if not line or line[0] in "=*#:;|!{" or line.lower().startswith(("[[category", "[[file", "[[image", "__")):
            continue
        s = clean_value(line)
        if len(s) > 30:
            return s
    return ""

_DATE_PH = r"(?:\x01[^\x02]*\x02|[^()]{4,40}?)"

def person_lead(lead):
    """(born X) / (X - Y) in the first parenthetical -> birth_date, death_date."""
    f = {}
    m = re.search(r"^[^()]{1,100}?\(([^()]{0,160})\)", lead)
    if not m:
        return f
    p = m.group(1)
    if re.search(r"\bca?\.|\bcirca\b|/|\bor\b", p, re.I):
        return f  # approximate or alternative dates: not reliable enough
    is_born = re.match(r"\s*(?:born|b\.)\s", p, re.I)
    ds = scan_dates(p)
    if not ds:
        return f
    if is_born:
        f["birth_date"] = (ds[0], "lead_text")
    elif re.search(r"\s[-–]\s|\bto\b|\s&ndash;\s|\x02\s*[-–]", p) and len(ds) >= 2 and not re.search(r"\b(?:reigned|r\.|ruled)\b", p, re.I):
        f["birth_date"] = (ds[0], "lead_text")
        f["death_date"] = (ds[1], "lead_text")
    elif re.search(r"\s[-–]\s", p) and len(ds) == 2:
        f["birth_date"], f["death_date"] = (ds[0], "lead_text"), (ds[1], "lead_text")
    return f

_PROF = re.compile(r"\b(?:is|was|were|are)\s+(?:an?|the)\s+([a-z][a-z \-]{2,60}?)(?=\s+(?:who|that|from|in|of|born|and was|and is|known|which|at|for|with|on)\b|[,.;]|$)", re.I)

def lead_occupation(lead):
    m = _PROF.search(re.split(r"(?<=[a-z])\.\s", lead[:260])[0])
    if m:
        v = m.group(1).strip().lower()
        if 1 <= len(v.split()) <= 5:
            return v
    return None

_EVT_LEAD = re.compile(r"\b(?:lasted|took place|happened|occurred|began|started|was fought|was held|ran|existed|ruled|were held)?\s*(?:from|in|on|between)\s+([^.;]{3,120})", re.I)

def event_lead(lead):
    s = re.sub(r"^[^.]*?\b(?:is|was|were|are)\b", "", lead[:300], count=1)
    m = re.search(r"\b(?:from|between)\s+(\x01[^\x02]*\x02|[^.;,]{3,60}?)\s+(?:to|until|and|-|–)\s+(\x01[^\x02]*\x02|[^.;,]{3,60}?)(?=[ .;,)]|$)", s, re.I)
    if m:
        ds = scan_dates(m.group(1)) + scan_dates(m.group(2))
        if len(ds) == 2:
            return ("%s/%s" % tuple(ds) if ds[0] != ds[1] else ds[0], "lead_text")
    m = re.search(r"\b(?:in|on)\s+((?:\d{1,2}\s+)?(?:%s\s+)?(?:\d{1,2},?\s+)?\d{3,4})\b" % _MON, s, re.I) or re.search(r"\x01([^\x02]*)\x02", s)
    if m:
        ds = scan_dates(m.group(0))
        if ds:
            return (ds[0], "lead_text")
    return None

_PLACE_KIND = r"(?:city|town|village|commune|municipality|county|state|province|region|district|river|mountain|island|lake|country|capital|department|canton|suburb|neighbourhood|national park|volcano|desert|peninsula|archipelago|sea|bay|area|prefecture|borough)"
_LOC_LEAD = re.compile(r"\b(?:is|was|are)\s+(?:an?|the)\s+(?:[a-z\-]+\s+){0,5}?%s\s+(?:\w+\s+){0,2}?(?:in|on|of|within|near|at)\s+(?:the\s+)?([A-Z][A-Za-z\-' ]{1,40}?(?:,\s*[A-Z][A-Za-z\-' ]{1,30})?)(?=[.,;(]|\s+(?:and|which|that|with|on|near|about|it|its|is|has|the|whose|where|located|north|south|east|west|in|of|by)\b|$)" % _PLACE_KIND)
_CAP_LEAD = re.compile(r"^(?:The\s+)?(.{2,40}?)\s+(?:is|was)\s+the\s+(?:capital|capital city)\s+(?:city\s+)?of\s+(?:the\s+)?([A-Z][A-Za-z\-' ]{1,40}?)(?=[.,;(]|\s+and\b|\s+which\b|\s+that\b|$)")

def location_lead(lead):
    m = _LOC_LEAD.search(lead[:300])
    return (m.group(1).strip(), "lead_text") if m else None

def capital_reverse(lead):
    """('Paris', 'France') from 'Paris is the capital of France' -> (capital-of target, capital name)"""
    m = _CAP_LEAD.match(lead[:200])
    if not m:
        return None
    return m.group(2).strip(), m.group(1).strip()

# ---- surname from the title (people only) ----
_PART = {"van", "von", "de", "der", "den", "di", "da", "del", "della", "du", "la", "le", "bin", "ibn", "al", "el", "ter", "ten", "dos", "das", "y", "mac"}
_SUFFIX = {"jr", "sr", "jr.", "sr.", "ii", "iii", "iv"}
_ROMAN = re.compile(r"^(?:[ivxlc]+)$", re.I)

def title_base(title):
    return re.sub(r"\s*\([^()]*\)\s*$", "", title).strip()

def surname_from_name(name):
    w = [x for x in re.sub(r"[,]", " ", name).split() if x]
    while w and w[-1].lower().rstrip(".") in _SUFFIX:
        w.pop()
    if len(w) < 2 or any(_ROMAN.match(x) and len(x) <= 4 and x.isupper() for x in w[1:]) or "of" in [x.lower() for x in w]:
        return None
    out = [w[-1]]
    i = len(w) - 2
    while i >= 1 and w[i].lower() in _PART:
        out.insert(0, w[i]); i -= 1
    return " ".join(out)

def surname(title, prm, lead_bold):
    """(value, prov) or None. Title wins when it is a plain 'Given Family' name; a mononymous title
    (Napoleon) takes the family name from an infobox full/birth name or the bold lead name that contains it."""
    tb = ascii_only(title_base(title))
    s = surname_from_name(tb)
    if s:
        return s, "title"
    for src, name in (("infobox", plain(prm.get("full_name", "") or prm.get("birth_name", ""))), ("lead_bold", lead_bold or "")):
        name = ascii_only(name)
        first = tb.split()[0].lower() if tb.split() else ""
        if name and first and first in [x.lower() for x in name.split()]:
            s = surname_from_name(name)
            if s and s.lower() != first:
                return s, src
    return None

def lead_bold(wt):
    m = re.search(r"'''+([^'\n]{2,60}?)'''+", re.sub(r"\{\{[^{}]*\}\}", "", wt))
    return ascii_only(re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", m.group(1))).strip() if m else ""

def extract(title, wt):
    """-> (etype, fields {rel: (value, prov)}, expected rels for missing markers, lead_cleaned)"""
    name, prm = infobox_params(wt)
    name = name or ""
    lead = lead_raw(wt)
    f = {}
    is_person = bool(prm.get("birth_date") or prm.get("born") or prm.get("death_date")) and not prm.get("conflict")
    if is_person:
        f.update(person_fields(prm))
    elif not name and re.match(r"^[^()]{1,100}?\((?:born|b\.)\s", lead, re.I) or (not name and re.match(r"^[^()]{1,100}?\([^()]*\d{3,4}[^()]*[-–][^()]*\d{3,4}[^()]*\)\s+(?:was|is)\s+(?:an?|the)\b", lead)):
        is_person = True
    if is_person:
        for k, v in person_lead(lead).items():
            f.setdefault(k, v)
        o = lead_occupation(lead)
        if o:
            f.setdefault("occupation", (o, "lead_text"))
        sn = surname(title, prm, lead_bold(wt))
        if sn:
            f["surname"] = sn
        return "person", f, ("birth_date", "birth_place", "death_date", "death_place", "surname", "occupation"), lead
    is_event = bool(_EVENT_BOX.search(name)) and not _PLACE_BOX.fullmatch(name)
    if is_event:
        f.update(event_fields(prm))
        if "date_range" not in f:
            e = event_lead(lead)
            if e:
                f["date_range"] = e
        return "event", f, ("date_range", "location"), lead
    if not name and re.search(r"\b(?:war|battle|siege|revolution|treaty|massacre|rebellion|earthquake|eruption)\b", title, re.I):
        e = event_lead(lead)
        if e:
            f["date_range"] = e
        return "event", f, ("date_range", "location"), lead
    if "capital" in prm or re.search(r"country|former country|sovereign|nation|republic|kingdom", name):
        f.update(place_fields(prm))
        return "country", f, ("capital", "quantity"), lead
    if _PLACE_BOX.search(name):
        f.update(place_fields(prm))
        if "location" not in f:
            loc = location_lead(lead)
            if loc:
                f["location"] = loc
        return "place", f, ("location", "quantity"), lead
    loc = location_lead(lead) if not name else None
    if loc:
        f["location"] = loc
        return "place", f, ("location",), lead
    return "other", f, (), lead
