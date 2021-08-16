import errno
import random
from CriticalExceptionM import CriticalException
import os
from typing import List
import subprocess
import time
import hashlib
import dbMan
import shutil
import multiprocessing


tempBinariesDirectory = os.path.join(os.getcwd(), 'TempBinaries')
gppCompiler = 'g++'
lockFileName = 'TesterLock.lck'

if os.path.exists(tempBinariesDirectory) == False:
    os.mkdir(tempBinariesDirectory)

def _compile_new_source(srcPath: str, srcHash: str) -> List[str]:
    "Compiles C# or C++ source code and adds it to the db."
    ext = os.path.splitext(srcPath)[1].lower()
    exe = ''
    if ext == '.cpp':
        exe = os.path.join(tempBinariesDirectory, f'{time.time_ns()}xyz{random.randint(1, 9999999)}.exe')
        args = [gppCompiler,  srcPath, '-static',  '-DONLINE_JUDGE', '-O2', '-std=c++17', '-o', exe]
        p = subprocess.run(
            args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(p.stdout)
        if p.returncode != 0:
            raise CriticalException(f"Couldn't compile file {srcPath} successfully")
    elif ext == '.cs' or ext == '.csx':
        DOTNET_FRAMEWORK = 'net5.0'
        projectPath, projectName = '', ''
        while True:
            for i in range(os.cpu_count()):
                projectName = f'project{i}'
                projectPath = os.path.join(
                    tempBinariesDirectory, 'CSharpProjects', projectName)
                if os.path.exists(projectPath) == False:
                    if subprocess.run(['dotnet', 'new', 'console', '-o', projectPath], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).returncode != 0:
                        raise CriticalException(f"Couldn't create a new C# project at '{projectPath}'.")
                    break
                lockPath = os.path.join(projectPath, lockFileName)
                if os.path.exists(lockPath) == False:
                    break
                projectPath = ''
            # a huge chance for a race condition
            if projectPath != '':
                break
        lockPath = os.path.join(projectPath, lockFileName)
        with open(lockPath, 'w') as fs:
            fs.write(str(multiprocessing.current_process().ident))
            fs.flush()
        programPath = os.path.join(projectPath, 'program.cs')
        shutil.copyfile(srcPath, programPath, follow_symlinks=True)
        csprojPath = os.path.join(projectPath, f'{projectName}.csproj')
        outputDir = os.path.join(
            tempBinariesDirectory, f'{time.time_ns()}xyz{random.randint(1, 9999999)}')
        if subprocess.run(['dotnet', 'build', '-c', 'Release', '-f', DOTNET_FRAMEWORK, '-o', outputDir, csprojPath], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).returncode != 0:
            os.remove(lockPath)
            raise CriticalException(f"Couldn't build project '{projectPath}'.")
        os.remove(lockPath)
        exe = os.path.join(outputDir, f'{projectName}.exe')

    with dbMan.getConnection() as con:
        con.execute('INSERT INTO Executable (sourceHash, path) VALUES (:sourceHash, :path);', {'sourceHash': srcHash, 'path': exe})
    return [exe]


def compile(srcPath: str) -> List[str]:
    "returns exe path and args that you must pass to exe"
    if os.path.exists(srcPath) == False:
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), srcPath)
    if os.path.isfile(srcPath) == False:
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), srcPath)
    ext = os.path.splitext(srcPath)[1].lower()
    if ext == '.exe':
        return [srcPath]
    elif ext == '.py':
        return ['python', srcPath]

    srcHash = ''
    with open(srcPath, 'r') as srcStream:
        src = srcStream.read()
        srcHash = hashlib.md5(src.encode('utf8'), usedforsecurity=False).hexdigest()
    with dbMan.getConnection() as con:
        exe = con.execute('SELECT path FROM Executable WHERE sourceHash = :srcHash', {'srcHash': srcHash}).fetchone()
        if exe != None:
            if os.path.exists(exe['path']):
                return [exe['path']]
            con.execute('DELETE FROM Executable WHERE sourceHash = :srcHash', {'srcHash': srcHash})

    return _compile_new_source(srcPath, srcHash)

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