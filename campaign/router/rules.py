#!/usr/bin/env python3
"""Rule baselines.  v0_gate is a line-by-line port of clean/plumbing/retrieve.c gate(); improved() is a hand-written
8-handler rule router written from the brief's failure list, then checked once on calib (no per-case tuning)."""
import re

STOP_CUE = "who what whats where when which define explain describe".split()
CODE_WORDS = set("list dict string function variable loop file command python code print return sort reverse count plus minus times divided multiplied percent".split())
NUM_WORDS = set("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million".split())
MATH_WORDS = set("half double twice triple quarter over sum product added add subtract subtracted multiply divide difference squared cubed and away take more less than".split())
CODE_CHARS = set('()[]{}="`_')


def _words(q):
    s = re.sub(r"[^a-z0-9]+", " ", "".join(c for c in q if ord(c) < 128).lower()).strip()
    return s, s.split()


def v0_gate(q):
    """True iff the shipped v0.1.0 gate would send the question to KB retrieval (cds_wants_context)."""
    if len(q) > 127:
        return False
    buf, ws = _words(q)
    if not ((ws and ws[0] in STOP_CUE) or buf.startswith("tell me about ")):
        return False
    if any(c in CODE_CHARS for c in q):
        return False
    if any(w in CODE_WORDS for w in ws) or (any(w in NUM_WORDS for w in ws) and any(w in MATH_WORDS for w in ws)):
        return False
    for i, c in enumerate(q):  # a quote that is not a contraction
        if c == "'" and (i == 0 or not q[i - 1].isalpha() or i + 1 >= len(q) or not q[i + 1].isalpha()):
            return False
    if re.search(r"\d\s*[-+*/%^]|[-+*/%^]\s*\d", q):
        return False
    return True


def v0_route(q):
    return "facts" if v0_gate(q) else "other"  # everything else goes to the same transformer, un-routed


GREET = r"(?:hi|hello|hey|yo|howdy|hiya|heya|greetings|good (?:morning|afternoon|evening)|sup|thanks|thank you|thx|ok|okay|ok thanks|cool)"
ACT = {
    "x": r"(?:thats (?:great|cool|nice)|have a good (?:day|one)|introduce yourself|great|good)",
    "greeting": r"(?:hi|hello|hey|yo|howdy|hiya|heya|sup|greetings|morning|good (?:morning|afternoon|evening)|hello there|hey there|hi there|hi chatds|hey chatds)",
    "thanks": r"(?:thanks|thank you|thx|ty|cheers|much appreciated|appreciate it|thank u)( .*)?",
    "bye": r"(?:bye|bye bye|goodbye|see ya|see you.*|later|gotta go|good night|cya|farewell|ttyl|talk to you later|im off.*|night night)",
    "how_are_you": r"(?:how are you.*|how r u|hows it going|whats up|how do you feel|how have you been|whats going on)",
    "ack": r"(?:ok|okay|cool|nice|i see|got it|alright|sounds good|makes sense|right|sure|great|awesome|lol|haha|wow|hmm|oh ok|oh i see|understood|yep)",
    "identity": r"(?:who are you|what are you|what is your name|whats your name|who made you|who built you|are you (?:a )?(?:robot|real|human|ai|bot|chatgpt).*|tell me about yourself)",
    "capabilities": r"(?:what can you do|what features.*|what can you help with|can you help me|help|what do you know|what can i ask you|how can you help|what are you good at|what do you do|what commands.*)",
    "repeat": r"(?:say that again|repeat that|what was that|come again|pardon|sorry what|huh|can you repeat.*|try again|thats wrong|that is wrong)",
}
UNSUP = r"\b(weather|news|stock|bitcoin|alarm|timer|remind me|email|text (?:my|him|her|mom)|call (?:my|him|her|mom)|play (?:some|a|the)|draw|picture|image of|photo|web\b|youtube|translate|poem|essay|what time|time is it|what is the time|what day|date today|president|trending|order a|book a|download|volume|wifi|calendar)\b"
SHELL = r"\b(bash|shell|terminal|linux|unix|command line|mkdir|chmod|grep|touch|pwd|ls|cd|cat|head|tail|wc|rm|mv|cp|file|files|folder|move|copy|remove|rename|search for|find files|contents of|go to)\b|\b\w+\.(txt|log|csv|md|py|sh|json|c|h|pdf|png|dat)\b|\b(directory|folder|first \d+ lines|last \d+ lines|lines in)\b"
PYTHON = r"\b(nums|scores|temps|grades|ages|prices|tags|names|totals|words|data|stack|queue|each item|every number|even numbers|add up|largest|smallest|average|duplicates|join|split|how many times|python|list|dict|dictionary|tuple|array|function|variable|loop|index|element|items?|append|string|integer|boolean|def|class|lambda|import|range|len)\b|[\[\]{}()=_]|\b(last|first) (item|element|value|entry)"
TEXT = r"\b(flip|delete all spaces|reverse|uppercase|lowercase|capitali[sz]e|title case|vowels?|consonants?|letters? in|alphabetical|backwards?|characters? in|words? in|spell|swap the case|alphabeti[sz]e)\b"
_NW = "|".join(NUM_WORDS)
CALC = (r"\d\s*[-+*/%^x]\s*\d|\b(plus|minus|times|divided by|multiplied by|multiply|mod|squared|percent of|take away|subtract|add)\b.*\b(\d+|" + _NW + r")\b"
        r"|\b(" + _NW + r")\b.*\b(plus|minus|times|divided|over|add|subtract|multiply)\b|\d+ ?% ?of")
CLARIFY = r"^(?:(?:sort|rename|print|delete|fix|run|copy|open|reverse|count|list|change|move|explain|do|tell me more|continue|why|how|and|what about).{0,12}|.*\b(it|that|this|them|the other one|second one)\??|what does it mean|what do you mean.*)$"
AMBIG = set("java jaguar mercury python ruby apple amazon mouse turkey mars pluto cell bat crane bark spring chrome rust swift cobra oracle saturn delta orange jupiter venus".split())
FACT_CUE = r"^(?:who|what|whats|where|when|which|how (?:many|tall|big|far|old|large)|define|describe|tell me about|capital|population|[a-z ]+ (?:born|died|birthday|last name|surname|occupation|job|capital))\b|\b(born|died|birthday|last name|surname|capital of|population of|birthplace|occupation|known for|years)\b"


def improved(q):
    t = re.sub(r"[^a-z0-9%+*/^'._\-\[\](){}= ]+", " ", q.lower()).strip()
    t = re.sub(r"\s+", " ", t)
    plain = re.sub(r"[^a-z0-9 ]+", "", t).strip()
    if not plain or not re.search(r"[aeiouy]", plain) and len(plain.split()) <= 2 and not re.search(r"\d", plain):
        return "unknown"
    if re.fullmatch(r"(.)\1{3,}", plain.replace(" ", "")):
        return "unknown"
    for a, rx in ACT.items():
        if re.fullmatch(rx, plain):
            return "facts"
    m = re.match(r"^(?:%s)\b[,!. ]*\s*(.+)$" % GREET, plain)  # greeting prefix must not swallow a task
    if m and len(m.group(1)) > 2:
        return improved(m.group(1))
    if plain in AMBIG or re.fullmatch(r"(?:what is|whats|tell me about|who is|define) (?:a |the )?(%s)" % "|".join(AMBIG), plain):
        return "clarify"
    if re.search(UNSUP, plain):
        return "unknown"
    if re.search(r"\b(and|then|also)\b", plain) and sum(bool(re.search(p, plain)) for p in (CALC, SHELL, TEXT, FACT_CUE)) >= 2:
        return "clarify"
    if re.search(r"\b(what is|whats|explain|why|how does|how do i|what does)\b.*\b(python)\b", plain) and re.search(r"\b(in python|python)\b", plain) and re.search(r"\b(list|function|loop|dictionary|exception|error|decorator|class|comprehension|tuple|range)\b|\d", plain):
        return "python"
    if re.search(r"\b(last|first) name\b|\bsurname\b", plain):
        return "facts"
    if re.search(r"\bprint\b.*\b(bash|shell)\b|\b(bash|shell)\b", plain) and not re.search(r"\bpython\b", plain):
        return "shell"
    if re.search(r"\bpython\b|\b(def|import|lambda)\b|[\[\](){}=_]", t):
        if re.search(r"\bpython\b", plain) and re.search(r"\bwhat is\b", plain) and len(plain.split()) <= 3:
            return "clarify"
        return "python"
    if re.search(CALC, t) and not re.search(r"\b(population|born|died|year|years|who|capital)\b", plain):
        return "calc"
    if re.search(TEXT, plain) and not re.search(r"\b(list|items?|elements?)\b", plain):
        return "text"
    if re.search(SHELL, plain):
        return "shell"
    if re.search(PYTHON, plain) and not re.search(FACT_CUE, plain):
        return "python"
    if re.fullmatch(CLARIFY, plain):
        return "clarify"
    if re.search(FACT_CUE, plain) or len(plain.split()) <= 4:
        return "facts"
    return "facts"
