import argparse
from argparse import FileType
from os.path import abspath
from typing import List
import dbMan
import subprocess
import logging
import os
import compiler
import time
from CriticalExceptionM import CriticalException
import colorama
from colorama import Fore, Style
_sep = '!@#$%^&*()_ABCDEFG'
class TestResult:
    __slots__ = 'input', 'output', 'answer', 'verdict', 'elapsed', 'comment', 'testId'

    @property
    def passed(self):
        return self.verdict == 'Accepted'

    @staticmethod
    def runTest(input: str, answer: str, exe: list, testId: str = None, validator: list = None, validatorSep: str = None, validatorAdditionalData: str = None):
        """validator will receive input, output, answer and additional info all seperated by --seperator.
        If answer is None or a whitespace then a validator must be provided"""
        if (answer == None or str.isspace(answer)) and validator == None:
            raise CriticalException('Parameter "answer" can\'t be None or a whitespace without providing a validator.')
        res = TestResult()
        res.answer = answer
        res.input = input
        res.testId = testId
        validator = None if validator == None else list(validator)
        try:
            res.elapsed = time.time_ns()
            proc = subprocess.run(exe, text=True, input=input, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout = 5, check=True)
        except subprocess.TimeoutExpired:
            res.elapsed = time.time_ns() - res.elapsed
            res.verdict = 'Timedout'
        except subprocess.CalledProcessError:
            res.elapsed = time.time_ns() - res.elapsed
            res.verdict = 'Non-zero exit'
        else:
            res.elapsed = time.time_ns() - res.elapsed
            res.output = proc.stdout.strip()
            if validator == None:
                if res.output == answer:
                    res.verdict, res.comment = 'Accepted', None
                else:
                    res.verdict, res.comment = 'Worng answer', "Output doesn't match answer"
            else:
                valProc = subprocess.run(validator, text=True, input=f'\n{validatorSep}\n'.join([input, res.output, answer, validatorAdditionalData]), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                if valProc.returncode == 0:
                    res.verdict, res.comment = 'Accepted', None
                else:
                    res.verdict, res.comment = 'Worng answer', valProc.stdout
        res.elapsed //= 1000000
        return res

    def __str__(self):
        l = []
        if self.testId != None:
            l.append(f'Test Id: {self.testId}') 
        l.append(f'verdict: {self.verdict}')
        l.append(f'elapsed: {self.elapsed}')
        if self.verdict != None:
            l.append(f'input:\n{self.input}') 
            l.append(f'output:\n{self.output}')
            l.append(f'answer:\n{self.answer}')
        return '\n'.join(l)
    def __repr__(self):
        return self.__str__()

def testProblem(userId: str, sourcePath: str, cfTestsIds: List[int] = None, uTestsIds: List[int] = None, validatorPath: str = None) -> None:
    prob = dbMan.Problem.getByUserId(userId)
    exe = compiler.compile(abspath(sourcePath))
    if validatorPath != None:
        val = compiler.compile(abspath(validatorPath))
        val.append(f'--seperator')
        val.append(_sep)
    else:
        val = None
    
    ts = dbMan.TestSet(prob.id, cfTestsIds, uTestsIds)
    if len(ts.tests) == 0:
        print(f'{Fore.RED}No tests where found{Fore.RESET}')
        return
    failedTests = []
    maxElapsed: TestResult = None
    for t in ts.tests:
        tr = TestResult.runTest(t.input, t.answer, exe, t.id, val, _sep)
        if tr.passed == False:
            failedTests.append(tr)
        if maxElapsed == None or tr.elapsed > maxElapsed.elapsed: maxElapsed = tr
    print(f'Ran {len(ts.tests)} tests, {len(ts.tests) - len(failedTests)} {Fore.GREEN}passed{Fore.RESET} and {len(failedTests)} {Fore.RED}failed{Fore.RESET}')
    print(f'Max elapsed test is {maxElapsed.testId} and it took {maxElapsed.elapsed}ms')
    if len(failedTests) > 0:
        print(f'{Fore.RED}Failed{Fore.RESET} tests ids are: {", ".join(str(t.testId) for t in failedTests)}')

def stressTest(sourcePath: str, n: int, generatorPath: str, outputPath: str, validatorPath: str = None, solverPath: str = None):
    """generator must first print the test case, answer(can be empty) and additional info(can be empty) for the validator all seperated by argument --seperator
    if a solver is provided then generator answer will be ignored and instead solver will be called and its answer will be provided to the validator"""

    exe, gen = compiler.compile(abspath(sourcePath)), compiler.compile(abspath(generatorPath))
    gen.append('--seperator')
    gen.append(_sep)
    if validatorPath != None:
        val = compiler.compile(abspath(validatorPath))
        val.append('--seperator')
        val.append(_sep)
    else:
        val = None
    
    sol = None if solverPath == None else compiler.compile(abspath(solverPath))

    allGood = True
    maxElapsed: TestResult = None
    for i in range(1, n + 1):
        print(f'Test case #{i}: ',end='')
        genProc = subprocess.run(gen, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
        gpo = compiler.splitOnLine(_sep, genProc.stdout, 3)
        sln = gpo[1] if sol == None else subprocess.run(sol, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True, input=gpo[0]).stdout.strip()
        t = TestResult.runTest(gpo[0], sln, exe, validator=val, validatorSep=_sep, validatorAdditionalData=gpo[2])
        if t.passed == False:
            with open(outputPath, 'a+') as opt:
                opt.write(('#' * 150) + '\n')
                opt.write(str(t))
                opt.write('\n' + ('#' * 150))
            print(f'{Fore.RED}Failed{Fore.RESET}, see file {outputPath} for additional info')
            allGood = False
            break
        if maxElapsed == None or t.elapsed > maxElapsed.elapsed: maxElapsed = t
        print(f'{Fore.GREEN}Passed{Fore.RESET}')
    if allGood == False: return
    print(f'Ran {n} tests {Fore.GREEN}successfully{Fore.RESET}')
    print(f'Max elapsed test took {maxElapsed.elapsed}ms')

def cmd(args: argparse.Namespace) -> bool:
    if args.subparserName == 'cfStressTest':
        if args.N <= 0: return True
        slnPath = os.path.join(compiler.tmp,f'problem{args.problemId}_{time.time_ns()}solution.cpp')
        with open(slnPath, 'w+') as slnFs:
            print('Downloading problem solution.')
            slnFs.write(dbMan.ProblemSln.cfLoadProblemSln(args.problemId).source)
            print('Done downloading.')
            slnFs.flush()
        stressTest(args.source, args.N, args.generator, f'problem{args.problemId}_{time.time_ns()}_FailedTestCase.txt', args.validator, slnPath)
        os.remove(slnPath)
        return True

    if args.subparserName == 'stressTest':
        if args.N <= 0: return True
        stressTest(args.source, args.N, args.generator, f'problem{args.problemId}_{time.time_ns()}_FailedTestCase.txt', args.validator, _sep)
        return True
    
    if args.subparserName == 'test':
        def splitTestsIds(strList: str) -> List[int]:
            res = []
            for i in (i.strip() for i in strList.split(',')):
                if ''.find('-') == -1: res.append(int(i))
                else:
                    s, e = [int(j.strip()) for j in i.split('-')]
                    res.extend(range(s, e + 1))
            return res
        cfTestsIds = splitTestsIds(args.cfTests) if args.cfTests else None
        uTestsIds  = splitTestsIds(args.uTests) if args.uTests else None
        testProblem(args.problemId, args.source, cfTestsIds, uTestsIds)
        return True
    
    return False

def addParser(p: argparse._SubParsersAction):
    pCFStressTest = p.add_parser('cfStressTest', description='Stress test a CF problem, by downloading any cpp solution then feeding it your generator test case after that it will compare CF solution to your\'s.')
    pCFStressTest.add_argument('problemId', help='Id of CF problem to stress test.')
    pCFStressTest.add_argument('N', help='Number of times to stress test your solution.', type=int)
    pCFStressTest.add_argument('source', help='Path to your solution file.')
    pCFStressTest.add_argument('generator', help='Path to your generator file, it must print the test case, answer(mostly empty), additional data for validator(can be empty) all seperated by argument --seperator.')
    pCFStressTest.add_argument('--validator', help='Path to your validator file, it will receive test case, your solution answer, CF solution answer, additional data from generator(can be empty) all seperated by argument --seperator.')

    pStressTest = p.add_parser('stressTest', description='Stress test a non-CF problem, by feeding it your generator test case after that it will feed case and output to validator.')
    pStressTest.add_argument('problemId', help='Id of CF problem to stress test.')
    pStressTest.add_argument('N', help='Number of times to stress test your solution.', type=int)
    pStressTest.add_argument('source', help='Path to your solution file.')
    pStressTest.add_argument('generator', help='Path to your generator file, it must print the test case, answer(can\'t be empty unless you provided a validator), additional data for validator(can be empty) all seperated by argument --seperator.')
    pStressTest.add_argument('--validator', help='Path to your validator file, it will receive test case, your solution answer, generator answer(can be empty), additional data from generator(can be empty) all seperated by argument --seperator.')

    pTest = p.add_parser('test', description='Runs a group of saved tests in the db against your solution.')
    pTest.add_argument('problemId', help='Id of the problem to test.')
    pTest.add_argument('source', help='Path to your solution file.')
    pTest.add_argument('--cfTests', help="Numbers of CF tests you want to run seperated by a comma and can include ranges and non-existing tasks numbers, ex: 1,2,4-6,10,13. If omitted then all will be tested.")
    pTest.add_argument('--uTests', help="Numbers of User tests you want to run seperated by a comma and can include ranges and non-existing tasks numbers, ex: 1,2,4-6,10,13. If omitted then all will be tested.")