# SPDX-License-Identifier: MIT
"""Pocket notebook prototype, independent integer twin of clean/plumbing/mathnb.c.
No eval(), libm, generated numeric output, dataset-derived grammar, or heap-sized
input. Public entry parse returns (0|1|-1, Spec); evaluate rejects whole requests.
"""
from dataclasses import dataclass, field
import re
SCALE, LIMIT, NODES, DEPTH, POINTS, BARS = 10000, 100000000, 32, 8, 129, 16
REFUSAL = 'Sorry, this notebook supports bounded expressions, ranges and lists only.'
CONST, X, ADD, SUB, MUL, DIV, POW, NEG, SIN, COS, SQRT, ABS = range(12)

@dataclass
class Spec:
    kind: int = 0
    ast: list = field(default_factory=list)  # (op,left,right,value), postorder
    root: int = 0
    points: int = POINTS
    lo: int = -5*SCALE
    hi: int = 5*SCALE
    bars: list = field(default_factory=list)

def rd(a, b):
    n, d = abs(a), abs(b)
    q = n//d + (2*(n%d) >= d)
    return -q if (a<0) != (b<0) else q

def validate(s):
    if s.kind not in (1,2,3): return False
    if s.kind == 2:
        return not s.ast and s.root == 0 and 1 <= s.points <= BARS and len(s.bars) == s.points and all(abs(v)<=LIMIT for v in s.bars)
    if not 1 <= s.points <= POINTS or not -100*SCALE <= s.lo <= s.hi <= 100*SCALE: return False
    if s.kind == 1 and (s.lo==s.hi or s.points<2): return False
    if s.kind == 3 and (s.points>16 or s.lo%SCALE or s.hi%SCALE or s.hi-s.lo!=(s.points-1)*SCALE): return False
    if not 1 <= len(s.ast) <= NODES or s.root != len(s.ast)-1: return False
    depths=[]
    for i,(op,l,r,v) in enumerate(s.ast):
        if not CONST <= op <= ABS or abs(v)>LIMIT: return False
        d=1
        if op>=ADD:
            if not 0<=l<i: return False
            d=depths[l]+1
            if op<=POW:
                if not 0<=r<i: return False
                d=max(d,depths[r]+1)
                if op==POW:
                    b=s.ast[r]; val=b[3]
                    if b[0]==NEG: val=-s.ast[b[1]][3]
                    if (b[0]==CONST or (b[0]==NEG and s.ast[b[1]][0]==CONST)) and (val%SCALE or abs(val)>8*SCALE): return False
        if d>DEPTH: return False
        depths.append(d)
    return True

class LimitError(ValueError):
    """Unambiguous notebook request exceeds an implementation bound."""

class Parser:
    def __init__(self,q,s): self.q,self.s,self.i=q,s,0
    def ws(self):
        while self.i<len(self.q) and self.q[self.i]==' ': self.i+=1
    def peek(self):
        self.ws(); return self.q[self.i:self.i+1]
    def word(self,w):
        self.ws()
        if not self.q.startswith(w,self.i): return False
        end=self.i+len(w)
        if end<len(self.q) and 'a'<=self.q[end]<='z': return False
        self.i=end; return True
    def number(self,signed=False):
        self.ws(); sign=1
        if signed and self.peek() in ('-','+'):
            sign=-1 if self.q[self.i]=='-' else 1; self.i+=1
        m=re.match(r'(\d+\.?\d*|\.\d+)',self.q[self.i:])
        if not m: raise ValueError('number')
        t=m[0]; self.i+=len(t); a,_,f=t.partition('.')
        v=int(a or '0')*SCALE+int((f+'0000')[:4])+(len(f)>4 and f[4]>='5')
        if v>LIMIT: raise LimitError('constant limit')
        return sign*v
    def node(self,op,l=0,r=0,v=0):
        if len(self.s.ast)>=NODES: raise LimitError('nodes')
        self.s.ast.append((op,l,r,v)); return len(self.s.ast)-1
    def atom(self,d):
        if d>DEPTH: raise LimitError('depth')
        ch=self.peek()
        if ch in ('-','+'):
            self.i+=1; a=self.expr(3,d+1); return self.node(NEG,a) if ch=='-' else a
        if ch=='(':
            self.i+=1; a=self.expr(0,d+1)
            if self.peek()!=')': raise ValueError('paren')
            self.i+=1; return a
        for name,op in [('sin',SIN),('cos',COS),('sqrt',SQRT),('abs',ABS)]:
            if self.word(name): return self.node(op,self.atom(d+1))
        if self.word('x') or self.word('n'): return self.node(X)
        return self.node(CONST,v=self.number())
    def expr(self,prec=0,d=0):
        a=self.atom(d)
        while True:
            ch=self.peek()
            if prec<=3:
                power=2 if self.word('squared') else 3 if self.word('cubed') else 0
                if power:
                    b=self.node(CONST,v=power*SCALE); a=self.node(POW,a,b); continue
            level={'+':1,'-':1,'*':2,'/':2,'^':3}.get(ch,0)
            if not level or level<prec: return a
            self.i+=1; b=self.expr(level+(ch!='^'),d+1)
            a=self.node({'+':ADD,'-':SUB,'*':MUL,'/':DIV,'^':POW}[ch],a,b)

def notebook_tokens(q):
    # Check the whole body before bounds, including prose beyond byte 127.
    words={'x','n','sin','cos','sqrt','abs','squared','cubed',
           'from','to','with','points','for'}
    for match in re.finditer(r'[a-zA-Z]+|[^a-zA-Z]',q):
        token=match[0]
        if token.isascii() and token.isalpha():
            if token.lower() not in words: return False
        elif ord(token)>=32 and token not in ' 0123456789.()+-*/^,?': return False
    return True

def parse(query):
    s=Spec(); q=''.join(chr(ord(c)+32) if 'A'<=c<='Z' else c for c in query[:127]); p=Parser(q,s)
    p.word('please')
    if p.word('can you') or p.word('could you'): p.word('please')
    if p.word('plot') or p.word('graph'): s.kind=1
    elif p.word('show bars for') or p.word('bars for') or p.word('bar chart of'): s.kind=2
    elif p.word('table of') or p.word('show table of') or p.word('make a table of'): s.kind=3
    else: return 0,s
    if not re.match(r' *(?:[0-9.(\-+]|(?:x|n|sin|cos|sqrt|abs)(?![a-z]))',q[p.i:]): return 0,s
    if not notebook_tokens(query[p.i:]): return 0,s
    if len(query)>127: return -1,s
    if any(not 32<=ord(c)<=126 for c in query): return 0,s
    fractional_count=False
    try:
        if s.kind==2:
            while True:
                if len(s.bars)==BARS: raise LimitError('bars')
                s.bars.append(p.number(True))
                if p.peek()!=',': break
                p.i+=1
            s.points=len(s.bars)
        else:
            s.root=p.expr()
            if s.kind==3:
                if not (p.word('for n') or p.word('for x')): raise ValueError('table range')
                p.word('from'); s.lo=p.number(True)
                if not p.word('to'): raise ValueError('to')
                s.hi=p.number(True); s.points=(s.hi-s.lo)//SCALE+1
            else:
                if p.word('from'):
                    s.lo=p.number(True)
                    if not p.word('to'): raise ValueError('to')
                    s.hi=p.number(True)
                if p.word('with'):
                    count=p.number(True)
                    if not p.word('points'): raise ValueError('points')
                    fractional_count=bool(count%SCALE)
                    s.points=count//SCALE
        if p.peek()=='?': p.i+=1
        if p.peek(): return 0,s
        if fractional_count or not validate(s): raise LimitError('spec')
        return 1,s
    except LimitError: return -1,s
    except ValueError: return 0,s

def sine(v):
    v=abs(v)%62832*(-1 if v<0 else 1)
    if v>31416: v-=62832
    if v<-31416: v+=62832
    if v>15708: v=31416-v
    if v<-15708: v=-31416-v
    term=total=v
    for i in range(1,6):
        term=-rd(term*v*v,SCALE*SCALE*(2*i)*(2*i+1)); total+=term
    return total

def evaluate(s):
    if not validate(s): raise ValueError('spec')
    result=[]
    for k in range(s.points):
        x=(k+1)*SCALE if s.kind==2 else s.lo if s.points==1 else s.lo+rd((s.hi-s.lo)*k,s.points-1)
        vals=[]
        for op,l,r,c in s.ast:
            a=vals[l] if op>=ADD else 0; b=vals[r] if ADD<=op<=POW else 0
            if op==CONST: v=c
            elif op==X: v=x
            elif op==ADD: v=a+b
            elif op==SUB: v=a-b
            elif op==MUL: v=rd(a*b,SCALE)
            elif op==DIV: v=rd(a*SCALE,b)
            elif op==NEG: v=-a
            elif op==ABS: v=abs(a)
            elif op==SIN: v=sine(a)
            elif op==COS: v=sine(a+15708)
            elif op==SQRT:
                if a<0: raise ValueError('domain')
                lo,hi=0,1000001; target=a*SCALE
                while lo+1<hi:
                    m=(lo+hi)//2
                    if m*m<=target: lo=m
                    else: hi=m
                v=lo+(target-lo*lo>=hi*hi-target)
            elif op==POW:
                if b%SCALE or abs(b)>8*SCALE: raise ValueError('exponent')
                e=b//SCALE; v=SCALE
                for _ in range(abs(e)):
                    v=rd(v*a,SCALE)
                    if abs(v)>LIMIT: raise ValueError('overflow')
                if e<0: v=rd(SCALE*SCALE,v)
            if abs(v)>LIMIT: raise ValueError('overflow')
            vals.append(v)
        result.append((x,s.bars[k] if s.kind==2 else vals[s.root]))
    return result

def answer(query):
    status,s=parse(query)
    if not status: return None
    if status<0: return REFUSAL
    try: evaluate(s)
    except (ValueError,ZeroDivisionError): return REFUSAL
    return 'Pocket math: '+{1:'plot',2:'bars',3:'table'}[s.kind]+f' ({s.points} points).'
