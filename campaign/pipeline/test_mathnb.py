# SPDX-License-Identifier: MIT
"""Authored prototype cases only; no sealed/custody/adversarial fixtures.
Run: nice -n 19 ionice -c3 python3 -m pytest -q campaign/pipeline/test_mathnb.py
"""
import ctypes as C
import hashlib
from pathlib import Path
import random
import subprocess
import pytest
import mathnb as m
ROOT=Path(__file__).resolve().parents[2]

# Authored accepted, non-trigger and bounded-notebook refusal cases.
POSITIVE=[lead+verb+expr+tail for lead in ('','please ','can you ')
          for verb in ('plot ','graph ')
          for expr,tail in [('x squared',' from -5 to 5'),('sin x',''),('cos(x)',' from -3 to 3'),('sqrt(abs(x))',' with 33 points'),('x/2+1',' from -10 to 10')]]
POSITIVE += [lead+verb+expr for lead in ('','please ','could you ')
             for verb in ('show bars for ','bars for ','bar chart of ')
             for expr in ('3, 8, 2, 6','-2, 0, 4.5','0')]
POSITIVE += [lead+verb+expr for lead in ('','please ','can you ')
             for verb in ('table of ','show table of ','make a table of ')
             for expr in ('2^n for n 1 to 8','n squared for n from -3 to 3','abs(x) for x -2 to 2')]
POSITIVE += ['GRAPH SIN X?', 'plot -x^2', 'plot x^-2 from 1 to 2', 'plot 0',
             'plot 1.00005', 'plot .5', 'plot x cubed', 'table of 2^n for n 0 to 0',
             'plot sin(cos(x))', 'plot x from -100 to 100 with 2 points',
             'plot -x squared', 'plot x*2 squared']
NEGATIVE=[
 'what is a plot','plot of hamlet','graph theory','plot of a movie','plot a story',
 'plot twist','table of contents','table of elements','bars of chocolate',
 'show bars for music','bar chart of sales','plot weather','plot y','graph tan x',
 'plot exp(x)','graph logarithms','plot pi','plot e','plot sine waves','graph sine x',
 'plotting x squared','plots x','graphing sin x','draw sin x','explain plot x',
 'what does graph sin x mean','how do I plot x','python plot x','shell graph x',
 'say "plot x"','reverse "graph x"','summarize a plot','help me graph x',
 'make a table','show a table','table of Hamlet','show table of names',
 'bar charts','bars for songs','show bars for a histogram','plot the function x',
 'plot something','graph that','plot it','a graph of x','chart x','scatter plot x',
 'what is 2+3','calculate 8/2','calc(2+3)','hi','who is Ada Lovelace',
 'plot ocean depth','table of population','graph isomorphism','plot Hamlet from 1 to 8',
 'please plot of hamlet','can you graph theory','could you table of contents','graph xyz']
# Every non-math example named in the review, including all eight false captures.
REVIEW_NEGATIVE=[
 'plot of hamlet','what is a bar','table of contents','graph theory','bars near me',
 'plot twist','x factor','plot summary','graph paper','table of elements',
 'plot new york times','plot 2001 a space odyssey','plot 1984 summary',
 'table of 12 for dinner','graph x marks the spot','plot x men','bars for 2 people',
 'bar chart of 3 types of cheese','graph 3 vs 4']
PROSE_NEGATIVE=[
 'plot 2001 explained','plot 1984 book ending','graph x axis meaning',
 'plot x files','graph n word usage','plot sin city','graph cos play',
 'plot abs workout','plot sqrt symbol meaning','table of 4 guests',
 'show table of 8 diners','make a table of 2 people','bars for 3 friends',
 'show bars for 4 tourists','bar chart of 2 drinks','plot 3 act structure',
 'graph 2 against 3','plot 1 chapter summary','plot 7 samurai',
 'plot 12 angry men','graph x and y in prose','plot n is a letter',
 'plot 1 from the movie','plot x from here to there','plot x with friends',
 'please graph 3 ways home','can you plot 2 story arcs',
 'could you show bars for 5 visitors','please table of 6 for lunch',
 'graph 4 vs 5','tell me plot x','for dinner table of 12',
 'plot x from -101 to 1 in the story','plot 10001 dalmatians',
 'bars for '+','.join(['1']*17)+' people',
 'plot '+('('*10)+'x'+(')'*10)+' in a film',
 'plot 1/0 means what','plot x^9 movie',
 'plot x '+' '*130+'in a story',
 'plot x from 0 to 1 junk','bars for 1 two','plot x + foo',
 'plot x; shell','plot 1e3','plot x from a to b','table of n for z 1 to 2',
 'plot x 2','bars for 1 2','table of 12 for points',
 'plot x with 130 points for n','plot x from -101 to 1 for n',
 'plot x^9 for n','table of n for n 1 to 17 for x',
 'plot (x','plot x)','plot x +','plot x**2','plot x from 0','bars for 1,',
 'table of n','plot x\nfrom 0 to 1','plot x from 0 to 1\t','plot nan']
NEGATIVE=list(dict.fromkeys(NEGATIVE+REVIEW_NEGATIVE+PROSE_NEGATIVE))
REFUSED=[
 'plot x from -101 to 1','plot x from 0 to 101','plot x from 5 to -5','plot x from 1 to 1',
 'plot x with 0 points','plot x with 1 points','plot x with 130 points','plot x with 2.5 points',
 'plot 10001','plot 999999999999999999999',
 'plot x^9','plot x^-9','plot x^0.5','plot x^x',
 'plot '+('('*10)+'x'+(')'*10),
 'plot '+'+'.join(['x']*33),'plot '+('-'*10)+'x',
 'bars for '+','.join(['1']*17),'bars for 10001',
 'table of n for n 1 to 17','table of n for n 2 to 1','table of n for n .5 to 2',
 'plot x with -2 points',
 'plot x '+' '*130,'plot x from -10000 to 10000',
 'plot sqrt(-1)','plot 1/0','plot x^8 from 10 to 11','plot x^-1']
CASES=[(q,1) for q in POSITIVE]+[(q,0) for q in NEGATIVE]+[(q,-1) for q in REFUSED]

class Node(C.Structure):
    _fields_=[('value',C.c_int32),('op',C.c_uint8),('left',C.c_uint8),('right',C.c_uint8),('reserved',C.c_uint8)]
class Spec(C.Structure):
    _fields_=[('kind',C.c_uint8),('nodes',C.c_uint8),('root',C.c_uint8),('reserved',C.c_uint8),('points',C.c_uint16),('lo',C.c_int32),('hi',C.c_int32),('ast',Node*32),('bars',C.c_int32*16)]
class Values(C.Structure):
    _fields_=[('x',C.c_int32*129),('y',C.c_int32*129)]
FB=C.c_uint16*(256*192)

@pytest.fixture(scope='session')
def lib(tmp_path_factory):
    path=tmp_path_factory.mktemp('mathnb')/'mathnb.so'
    subprocess.run(['nice','-n','19','ionice','-c3','cc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    '-I'+str(ROOT/'clean/plumbing'),'-I'+str(ROOT/'clean/ui/include'),str(ROOT/'clean/plumbing/mathnb.c'),str(ROOT/'clean/plumbing/mathnb_render.c'),
                    str(ROOT/'clean/ui/src/ui_font.c'),'-o',str(path)],check=True)
    dll=C.CDLL(str(path))
    dll.mnb_parse.argtypes=[C.c_char_p,C.POINTER(Spec)]
    dll.mnb_validate.argtypes=[C.POINTER(Spec)]
    dll.mnb_evaluate.argtypes=[C.POINTER(Spec),C.POINTER(Values)]
    dll.mnb_render.argtypes=[C.POINTER(Spec),C.POINTER(Values),C.POINTER(C.c_uint16)]
    return dll

def effective(q):
    status,s=m.parse(q)
    if status==1:
        try: return status,s,m.evaluate(s)
        except (ValueError,ZeroDivisionError): return -1,s,None
    return status,s,None

@pytest.mark.parametrize('query,expected',CASES)
def test_authored(lib,query,expected):
    status,s,values=effective(query)
    c=Spec(); v=Values(); parsed=lib.mnb_parse(query.encode(),C.byref(c))
    evaluated=lib.mnb_evaluate(C.byref(c),C.byref(v)) if parsed==1 else 0
    cs=-1 if parsed==1 and not evaluated else parsed
    assert status==expected,query
    assert cs==status,query
    assert parsed==m.parse(query)[0],query
    if status==1:
        assert (c.kind,c.nodes,c.root,c.points,c.lo,c.hi)==(s.kind,len(s.ast),s.root,s.points,s.lo,s.hi)
        assert [(n.op,n.left,n.right,n.value) for n in c.ast[:c.nodes]]==s.ast
        assert list(zip(v.x[:c.points],v.y[:c.points]))==values
        assert lib.mnb_render(C.byref(c),C.byref(v),FB())==1

def test_count():
    assert len(CASES)>=150 and len({q for q,_ in CASES})==len(CASES)

def test_request_fuzz_twin(lib):
    rng=random.Random(24024)
    pieces=['x','n','sin ','cos ','sqrt ','abs ','(',')','+', '-', '*', '/', '^',
            '1','0','.00005','10001',' squared',' cubed',' from ',' to ',' with ',' points',',','foo','?', '\\t','é','İ']
    for _ in range(5000):
        query=rng.choice(['plot ','graph ','table of ','bars for ','what is a plot '])+''.join(rng.choices(pieces,k=rng.randrange(1,40)))
        c=Spec()
        assert lib.mnb_parse(query.encode(),C.byref(c))==m.parse(query)[0],repr(query)

@pytest.mark.parametrize('expr', ['x+2','x-2','x*2','x/3','x^3','-x^2','x^-2','abs(x)','sqrt(abs(x))','sin x','cos x','sin(cos(x))'])
def test_numeric_twin(lib,expr):
    for lo,hi in [(-5,5),(1,3),(-100,100)]:
        q=f'plot {expr} from {lo} to {hi}'
        status,s,vals=effective(q); c=Spec();v=Values()
        assert lib.mnb_parse(q.encode(),C.byref(c))==1
        ok=lib.mnb_evaluate(C.byref(c),C.byref(v))
        assert bool(ok)==(status==1)
        if ok: assert list(zip(v.x[:c.points],v.y[:c.points]))==vals

def test_product_dispatch_no_generator(tmp_path):
    # Public main has no private host_pipeline. Exercise the shipped C product
    # with synthetic assets instead; the independent Python evaluator supplies
    # expected answers, and every notebook row must have zero generated IDs.
    import importlib.util
    spec = importlib.util.spec_from_file_location('product_fixture', ROOT/'clean/product/test_product.py')
    product = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(product)
    subprocess.run(['nice','-n','19','ionice','-c3','make','-j2','-C',ROOT/'clean/product','host'],check=True)
    queries = [*EXAMPLES.values(), 'repeat that', 'what is 2+3']
    script = 'R\n' + ''.join('Q\t'+q+'\n' for q in queries)
    result, _ = product.invoke(ROOT/'clean/product/build/chatds-host', tmp_path,
                              'steps=2\nkbd=0\ninstruct=1\nprompt=hello\n', serve=script)
    assert result.returncode == 0, result.stderr
    rows = [line.split('\t') for line in result.stdout.splitlines()]
    assert len(rows) == len(queries)
    for row, query in zip(rows[:4], queries):
        assert row[1:3] == ['mathnb', m.answer(query)]
        assert row[7:9] == ['0', '']
    assert rows[4][2] == m.answer(EXAMPLES['table'])
    assert rows[5][1:3] == ['calculator', 'calc(2+3) = 5']

def test_known_numbers():
    assert m.evaluate(m.parse('table of 2^n for n 1 to 8')[1])==[(n*10000,2**n*10000) for n in range(1,9)]
    assert m.evaluate(m.parse('plot -x^2 from 2 to 3 with 2 points')[1])==[(20000,-40000),(30000,-90000)]
    assert m.evaluate(m.parse('plot -x squared from 2 to 3 with 2 points')[1])==[(20000,-40000),(30000,-90000)]
    assert m.evaluate(m.parse('plot x*2 squared from 2 to 3 with 2 points')[1])==[(20000,80000),(30000,120000)]
    assert m.sine(0)==0 and m.sine(15708)==10000
    # Fixed recurrence accuracy is checked, not libm used for execution.
    import math
    assert max(abs(m.sine(i)/10000-math.sin(i/10000)) for i in range(-1000000,1000001,319))<0.0005

@pytest.mark.parametrize('field,value',[('kind',99),('nodes',33),('root',32),('points',130),('reserved',1),('lo',-1000001),('hi',1000001)])
def test_invalid_spec(lib,field,value):
    c=Spec();lib.mnb_parse(b'plot x',C.byref(c));setattr(c,field,value)
    assert not lib.mnb_validate(C.byref(c))
    fb=FB(*([123]*len(FB())))
    assert not lib.mnb_render(C.byref(c),C.byref(Values()),fb)
    assert all(x==123 for x in fb)

def test_mutated_nodes(lib):
    for op in range(256):
        c=Spec();lib.mnb_parse(b'plot x+1',C.byref(c));c.ast[c.root].op=op;c.ast[c.root].left=255
        v=Values(); valid=lib.mnb_validate(C.byref(c));ok=lib.mnb_evaluate(C.byref(c),C.byref(v))
        assert not ok or valid
    rng=random.Random(24)
    for _ in range(2000):
        c=Spec.from_buffer_copy(rng.randbytes(C.sizeof(Spec)))
        assert not lib.mnb_evaluate(C.byref(c),C.byref(Values()))

EXAMPLES={'square':'plot x squared from -5 to 5','sine':'graph sin x','bars':'show bars for 3, 8, 2, 6','table':'table of 2^n for n 1 to 8'}
# Frozen host PPM hashes. Updating requires deliberate visual/numeric review.
GOLDENS={
    'square':'85af6f38fbce311eeb98b9a7ed02144ef504e5716a1ac3efa0238ea33450f573',
    'sine':'08b080076b280fd128a68deb609b6aa9ac287c76bcf80d82f26fcb4db1199705',
    'bars':'5a27e805771a97da38e4c77907c4f6e2544f5269b2c477f173f7e63ed0c65a67',
    'table':'2ab851a4f901e22db6b1a104de7d8a8e99170d4391ec499b0b2414f797b71a6a',
}

def ppm(fb):
    return b'P6\n256 192\n255\n'+bytes(channel*255//31 for px in fb for channel in (px&31,(px>>5)&31,(px>>10)&31))

@pytest.mark.parametrize('name,query',EXAMPLES.items())
def test_golden(lib,name,query):
    c=Spec();v=Values();fb=FB()
    assert lib.mnb_parse(query.encode(),C.byref(c))==1
    assert lib.mnb_evaluate(C.byref(c),C.byref(v))
    assert lib.mnb_render(C.byref(c),C.byref(v),fb)
    assert hashlib.sha256(ppm(fb)).hexdigest()==GOLDENS[name]
