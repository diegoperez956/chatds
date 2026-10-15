#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Render host PPM/PNG and print hashes; does not update frozen test goldens."""
import ctypes as C
import hashlib
from pathlib import Path
import subprocess
import sys
import struct
import zlib
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'campaign/pipeline'))
import test_mathnb as t

def png_rgb(rgb, width=256, height=192):
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+rgb[y*width*3:(y+1)*width*3] for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows,9))+chunk(b'IEND',b'')

def main():
    work=ROOT/'build/mathnb';work.mkdir(parents=True,exist_ok=True)
    so=work/'mathnb.so'
    subprocess.run(['nice','-n','19','ionice','-c3','cc','-std=c99','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    '-I'+str(ROOT/'clean/plumbing'),'-I'+str(ROOT/'clean/ui/include'),
                    str(ROOT/'clean/plumbing/mathnb.c'),str(ROOT/'clean/plumbing/mathnb_render.c'),str(ROOT/'clean/ui/src/ui_font.c'),'-o',str(so)],check=True)
    lib=C.CDLL(str(so));out=ROOT/'campaign/results/mathnb';out.mkdir(parents=True,exist_ok=True)
    for name,q in t.EXAMPLES.items():
        s=t.Spec();v=t.Values();f=t.FB()
        assert lib.mnb_parse(q.encode(),C.byref(s))==1
        assert lib.mnb_evaluate(C.byref(s),C.byref(v))
        assert lib.mnb_render(C.byref(s),C.byref(v),f)
        data=t.ppm(f);p=work/(name+'.ppm');p.write_bytes(data)
        (out/('host-'+name+'.png')).write_bytes(png_rgb(data.split(b'\n',3)[3]))
        print(name,hashlib.sha256(data).hexdigest())
if __name__=='__main__':main()
