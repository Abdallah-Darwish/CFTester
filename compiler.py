from typing import List
import sys
from CriticalExceptionM import CriticalException
import os
import time
import random
import subprocess
tmp = os.path.join(os.getcwd(), 'TempBinaries\\')
if os.path.exists(tmp) == False:
    os.mkdir(tmp)
def compile(srcPath: str) -> list:
    "returns exe path and args that you must pass to exe"
    if os.path.exists(srcPath) == False:
        raise CriticalException(f"Can't find file: {srcPath}")
    if os.path.isfile(srcPath) == False:
        raise CriticalException(f"Path {srcPath} isn't a file")
    ext = os.path.splitext(srcPath)[1].lower()
    if ext == '.exe': return [srcPath]
    if ext == '.cpp': 
        exe = os.path.join(tmp, f'{time.time_ns()}xyz{random.randint(1, 9999999)}.exe')
        args = [r'C:\MinGW\bin\g++.exe',  srcPath , '-static',  '-DONLINE_JUDGE', '-Wl,--stack=268435456', '-O2', '-std=c++17' ,'-o', exe]
        p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if p.returncode != 0:
            print(p.stdout)
            print(' '.join(args))
            raise CriticalException(f"Couldn't compile file {srcPath} successfully")
        return [exe]
    elif ext == '.py':
        return ['python', srcPath]
    # no C# cause you must create project to build

def splitOnLine(sep:str, ipt: str = None, minLen = 0) -> List[str]:
    if ipt == None:
        ipt = sys.stdin.read()
    ipt = ipt.splitlines(keepends=False)
    res = []
    cstr = ''
    sepCnt = 0
    for ln in ipt:
        if ln == sep:
            res.append(cstr.strip())
            cstr = ''
        else:
            if len(cstr) > 0: cstr += '\n'
            cstr += ln
    if cstr != '': res.append(cstr.strip())
    if len(res) < sepCnt + 1: res.extend([''] * ((sepCnt + 1)- len(res)))
    if len(res) < minLen: res.extend([''] * (minLen - len(res)))
    return res
    
