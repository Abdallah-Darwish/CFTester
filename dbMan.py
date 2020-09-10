from typing import Dict, List, Tuple
from CriticalExceptionM import CriticalException
import sqlite3
import os
import requests
import bs4
import subprocess
from sessionMan import cfSession
from datetime import datetime
import compiler
import argparse
DB_NAME = 'cfdb.sqlite'
def getConnection() -> sqlite3.Connection:
    c = sqlite3.connect(DB_NAME)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys = ON')
    return c

if os.path.exists(DB_NAME) == False:
    with getConnection() as con:
        con.executescript("""
CREATE TABLE Problem (
    id INTEGER PRIMARY KEY NOT NULL,
    userId TEXT NOT NULL UNIQUE,
    /*IF not null then its CF*/
    contestId INTEGER DEFAULT(NULL),
    problemIdx TEXT DEFAULT(NULL)
);
CREATE TABLE Test (
    problemId INTEGER NOT NULL REFERENCES Problem(id),
    id Text NOT NULL,
    input TEXT NOT NULL,
    answer TEXT,
    PRIMARY KEY(problemId, id)
);
/*for CF problems only and has cpp slns only*/
CREATE TABLE ProblemSln (
    problemId INTEGER NOT NULL PRIMARY KEY REFERENCES Problem(id),
    source TEXT NOT NULL
);
        """)


class Problem:
    __slots__ = ('id', 'userId', 'contestId', 'problemIdx')
    def __init__(self, id: int):
        with getConnection() as con:
            r = con.execute('SELECT * FROM Problem WHERE id = :id', {'id': id}).fetchone()
            self.id, self.userId, self.contestId, self.problemIdx = id, r['userId'], r['contestId'], r['problemIdx']
    @staticmethod
    def getByUserId(userId: str):
        with getConnection() as con:
            r = con.execute('SELECT id FROM Problem WHERE userId = :uid', {'uid': userId}).fetchone()
            if r == None: return None
            return Problem(r['id'])
    @staticmethod
    def addProblem(userId: str, contestId: int, problemIdx: str):
        if problemIdx != None:
            problemIdx = problemIdx.upper()
        pid = 0
        with getConnection() as con:
            pid = con.execute('INSERT INTO Problem(userId, contestId, problemIdx) VALUES(:uid, :cid, :pidx)', {'uid': userId, 'cid' : contestId, 'pidx' : problemIdx}).lastrowid

        return Problem(pid)
    
    @staticmethod
    def getByContestId(contestId: int) -> list:
        with getConnection() as con:
            return [Problem(r[0]) for r in con.execute('SELECT id FROM Problem WHERE contestId = :cid', {'cid': contestId}).fetchall()]
    
    @staticmethod
    def cfAddContest(contestId: int, problemUserIdPrefix: str = None) -> list:
        if problemUserIdPrefix == None: problemUserIdPrefix = str(contestId)
        probs = cfSession.get(f'https://codeforces.com/api/contest.standings?contestId={contestId}&from=1&count=1&showUnofficial=false').json()['result']['problems']
        res = []
        for p in probs:
            res.append(Problem.addProblem(f'{problemUserIdPrefix}{p["index"]}', contestId, p["index"]))
        return res
            
class Test:
    'Answer may be None or whitespace because this is a generator & validator case'
    __slots__ = ('problemId', 'id', 'input', 'answer')
    def __init__(self, r: sqlite3.Row):
        self.problemId, self.id, self.input, self.answer = r['problemId'], r['id'], r['input'], r['answer']

def _findAcceptedSub(contestId: int, problemIdx: str, contestStands: dict) -> int:
    problemIdx = problemIdx.upper()
    probs = contestStands['problems']
    propOffset = next((i for i in range(len(probs)) if probs[i]['index'].upper() == problemIdx), -1)
    if propOffset == -1:
        raise CriticalException(f"Can't find problem {problemIdx} in contest {contestId}")
    probSolvers = [s['party']['members'][0]['handle'] for s in contestStands['rows'] if s['problemResults'][propOffset]['points'] > 0]

    def tryFindAcceptedSub(solverHandle: str) -> int:
        solverSubs = cfSession.get( f'https://codeforces.com/api/contest.status?contestId={contestId}&handle={solverHandle}&from=1&count=100000').json()['result']
        return next((s['id'] for s in solverSubs if s['problem']['index'].upper() == problemIdx and s['verdict'] == 'OK' and s['programmingLanguage'].find('++') != -1), -1)
   
    for h in probSolvers:
        subId = tryFindAcceptedSub(h)
        if subId != -1: return subId
    raise CriticalException(f"Can't find any accepted submission for problem {problemIdx} in contest {contestId}")
class TestSet:
    __slots__ = ('problemId', 'userId', 'contestId', 'problemIdx', 'tests')

    def __init__(self, pid: int, cfTestsIds: List[int] = None, uTestsIds: List[int] = None):
        self.problemId, self.tests = pid, []
        with getConnection() as con:
            # get members
            c = con.execute('SELECT * FROM Problem WHERE id = :pid', {'pid': pid})
            data = c.fetchone()
            self.userId, self.contestId, self.problemIdx = data['userId'], data['contestId'], data['problemIdx']

            # get tests
            cfTestsIdsCondition = "id LIKE 'CF%'" if cfTestsIds == None else '1 = 0'
            if cfTestsIds != None and len(cfTestsIds) > 0:
                cfTestsIdsCondition = 'id IN (' + ', '.join( f"'CF{i}'" for i in cfTestsIds) + ')'
            
            uTestsIdsCondition = "id LIKE 'U%'" if uTestsIds == None else '1 = 0'
            if uTestsIds != None and len(uTestsIds) > 0:
                uTestsIdsCondition = 'id IN (' + ', '.join( f"'U{i}'" for i in uTestsIds) + ')'
            
            testsQuery = f'SELECT * FROM Test WHERE problemId = :pid AND ({cfTestsIdsCondition} OR {uTestsIdsCondition})'
            c = con.execute(testsQuery, {'pid': pid})
            for r in c.fetchall():
                self.tests.append(Test(r))

    @staticmethod
    def _parseAndStoreSubmissionTests(contestId: int, subId: int, problemId: int, trans: list = None, transSep: str = None) -> int:
        'trans will receive each test case input and output seperated by transSep and its supposed to print the same'
        bs = bs4.BeautifulSoup(cfSession.get(f'https://codeforces.com/contest/{contestId}/submission/{subId}').text, 'lxml')

        xcsrf = bs.select_one('meta[name="X-Csrf-Token"]').get('content')
        d = cfSession.post('https://codeforces.com/data/submitSource',
                           headers={
                               'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                               'X-Csrf-Token': xcsrf
                           },
                           data=f'submissionId={subId}&csrf_token={xcsrf}').json()
        cnt = 0
        with getConnection() as con:
            for i in range(1, int(d['testCount']) + 1):
                ipt, opt = d[f'input#{i}'].replace('\r\n', '\n').strip(), d[f'answer#{i}'].replace('\r\n', '\n').strip()
                if trans != None:
                    transInput = f'{ipt}\n{transSep}\n{opt}'
                    ipt, opt = compiler.splitOnLine(transSep, subprocess.run(trans, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True, input=transInput).stdout, 2)
                elif ipt.endswith('...') or opt.endswith('...'):
                    ipt, opt = None, None
                if ipt != None and (str.isspace(ipt) == False) and opt != None and (str.isspace(opt) == False):
                    cnt += 1
                    con.execute('INSERT INTO Test(problemId, id, input, answer) VALUES(:problemId, :id, :input, :answer)',
                                {'problemId': problemId, 'id': f'CF{i}', 'input': ipt, 'answer': opt})
        
        return cnt

    @staticmethod
    def _parseAndStoreProblemSamples(contestId: int, probIdx: int, problemId: int) -> int:
        bs = bs4.BeautifulSoup(cfSession.get(f'https://codeforces.com/contest/{contestId}/problem/{probIdx}').text, 'lxml')

        samplesDiv: bs4.Tag = bs.select_one('div.sample-tests')
        inputs = samplesDiv.select('div.input>pre')
        outputs = samplesDiv.select('div.output>pre')
        with getConnection() as con:
            for i in range(len(inputs)):
                con.execute('INSERT INTO Test(problemId, id, input, answer) VALUES(:problemId, :id, :input, :answer)',
                            {'problemId': problemId, 'id': f'CF{i+1}', 'input': inputs[i].text, 'answer': outputs[i].text})
        return len(inputs)
    
   
    @staticmethod
    def cfLoadTestSet(userId: str, transformerPath: str = None) -> int:
        with getConnection() as con:
            r = con.execute('SELECT id, contestId, problemIdx FROM Problem WHERE userId = :userId', {'userId' : userId}).fetchone()
            pid, contestId, problemIdx = None, None, None
            if r != None:
                pid, contestId, problemIdx = r[0], r[1], r[2]
                con.execute("DELETE FROM Test WHERE problemId = :pid AND id LIKE 'CF%'", {'pid' : pid})
                con.commit()
            else:
                raise CriticalException(f'There is no problem with id: {userId} id DB')
            stands = cfSession.get(f'https://codeforces.com/api/contest.standings?contestId={contestId}&from=1&count=10&showUnofficial=true').json()['result']
            loadSamples = stands['contest']['phase'].lower() != 'finished'
            if loadSamples == False:
                # XLOG
                acc = _findAcceptedSub(contestId, problemIdx, stands)
                if acc != None:
                    con.commit()
                    if transformerPath != None:
                        trans, transSep = compiler.compile(transformerPath), '!@#$%^&*()_'
                        trans.append('--seperator')
                        trans.append(transSep)
                    else:
                        trans, transSep = None, None
                    return TestSet._parseAndStoreSubmissionTests(contestId, acc, pid, trans, transSep)
                else:
                    loadSamples = True

            if loadSamples:
                # XLOG
                return TestSet._parseAndStoreProblemSamples(contestId, problemIdx, pid)
            
    @staticmethod
    def loadTestSet(userId: str, tests: list) -> Tuple[str, str]:
        'tests : [(ipt, opt)]'
        problemIdx = userId.lower()

        with getConnection() as con:
            r = con.execute('SELECT id FROM Problem WHERE userId = :userId', {'userId' : userId}).fetchone()
            if r == None:
                # XLOG
                return
            pid = r[0]
            r = con.execute("SELECT max(CAST(SUBSTR(id, 2) AS INTEGER)) FROM Test WHERE problemId = :pid AND id LIKE 'U%'", {'pid' : pid}).fetchone()
            i = 1 if r == None else (r[0] + 1)
            i0 = i
            for t in tests:
                con.execute('INSERT INTO TEST(problemId, id, input, answer) VALUES(:pid, :id, :ipt, :ans)', {'pid' : pid, 'id' : f'U{i}', 'ipt' : t[0], 'ans' : t[1]})
                i += 1
            return (f'U{i0}', f'U{i - 1}')

class ProblemSln:
    __slots__ = 'problemId', 'source'

    def __init__(self, pid: int):
        with getConnection() as con:
            r = con.execute('SELECT source FROM ProblemSln WHERE problemId = :pid', {'pid' : pid}).fetchone()
            self.problemId, self.source = pid, r[0]
    
    @staticmethod
    def _parseAndstoreSubmissionSln(contestId: int, subId: int, problemId: int) -> None:
        bs = bs4.BeautifulSoup(cfSession.get(f'https://codeforces.com/contest/{contestId}/submission/{subId}').text, 'lxml')

        xcsrf = bs.select_one('meta[name="X-Csrf-Token"]').get('content')
        d = cfSession.post('https://codeforces.com/data/submitSource',
                           headers={
                               'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                               'X-Csrf-Token': xcsrf
                           },
                           data=f'submissionId={subId}&csrf_token={xcsrf}').json()
        with getConnection() as con:
            con.execute('INSERT INTO ProblemSln(problemId, source) VALUES(:pid, :src)', {'pid' : problemId, 'src' : d['source'].replace('\r\n', '\n') })
    
    @staticmethod
    def cfLoadProblemSln(userId: str):
        with getConnection() as con:
            r = con.execute('SELECT id, contestId, problemIdx FROM Problem WHERE userId = :userId', {'userId' : userId}).fetchone()
            pid, contestId, problemIdx = None, None, None
            if r != None:
                pid, contestId, problemIdx = r[0], r[1], r[2]
                if con.execute('SELECT problemId FROM ProblemSln WHERE problemId = :pid', {'pid' : pid}).fetchone() != None:
                    return ProblemSln(pid)
            else:
                raise CriticalException(f'There is no problem with Id = {userId}')
            stands = cfSession.get(f'https://codeforces.com/api/contest.standings?contestId={contestId}&from=1&count=10&showUnofficial=true').json()['result']
            if stands['contest']['phase'].lower() != 'finished':
                raise CriticalException(f'The contest is not finished yet, so can\'t download any solutions yet')
            ProblemSln._parseAndstoreSubmissionSln(contestId, _findAcceptedSub(contestId, problemIdx, stands), pid)
            return ProblemSln(pid)


def cmd(args: argparse.Namespace) -> bool:
    if args.subparserName == 'addProblem':
        Problem.addProblem(args.problemid, None, None)
        return True
    if args.subparserName == 'cfAddProblem':
        url = args.url.split('/')
        x = []
        contestId = int(url[url.index('contest') + 1])
        problemIdx = None if url.count('problem') == 0 else url[url.index('problem') + 1]
        if problemIdx == None:
            probs = Problem.cfAddContest(contestId, args.contestId)
            print(f'Added {len(probs)} with ids: {", ".join(p.id for p in probs)}') 
        else:
            uid = args.problemId if args.problemId else f'{contestId}{problemIdx}'
            Problem.addProblem(uid, contestId, problemIdx)
            print(f'Added 1 problem with id = {uid}')
        return True
    if args.subparserName == 'cfLoadTestset':
        if args.problemId:
            print(f'Loaded {TestSet.cfLoadTestSet(args.problemId, args.transformer)} tests')
        else:
            probs = Problem.getByContestId(int(args.contestId))
            for p in probs:
                print(f'Loading problem {p.id} tests')
                print(f'Loaded {TestSet.cfLoadTestSet(p.id)} tests')
        return True
    if args.subparserName == 'loadTestset':
        with open(args.setPath, 'r') as st:
            if args.testsSeperator:
                tests = [compiler.splitOnLine(args.IOSeperator, t) for t in compiler.splitOnLine(args.testsSeperator, st.read())]
            else:
                tests = [compiler.splitOnLine(args.IOSeperator, st.read())]
        if len(tests) > 0:
            x = TestSet.loadTestSet(args.problemId, tests)
            if x[0] == x[1]:
                print(f'Loaded 1 test with id = {x[0]}')
            else:
                print(f'Loaded tests {x[0]}..{x[1]}')
        else:
            print('No tests where loaded')
        return True
    return False

def addParser(p: argparse._SubParsersAction):
    pAddProblem = p.add_parser('addProblem', description='Adds a on-cf problem to the db.')
    pAddProblem.add_argument('problemId', help='Id of the new problem to add.')

    pCFAddProblem =p.add_parser('cfAddProblem', description='Adds a cf problem or contest to the db, but doesn\'t download the cases or anything.')
    pCFAddProblem.add_argument('url', help='Url of the problem or contest to add, but link must be from the contest not the problem set.')
    pCFAddProblemIdsGroup = pCFAddProblem.add_mutually_exclusive_group()
    pCFAddProblemIdsGroup.add_argument('--contestId', help='In case the its a contest url this argument will prefix all of the contest problems ids, by default it will be the contest id.')
    pCFAddProblemIdsGroup.add_argument('--problemId', help='In case the its a problem url this argument will be the id of the new problem, by default its ContestId+ProblemIdx.')

    pCFLoadTestSet = p.add_parser('cfLoadTestset', description='Loads a CF problem or contest test set from CF and stores it in db.')
    pCFLoadTestSetIdsGroup = pCFLoadTestSet.add_mutually_exclusive_group(required=True)
    pCFLoadTestSetIdsGroup.add_argument('--contestId', help='Id of the contest to load test sets for all the problems that belong to it in the db.')
    pCFLoadTestSetIdsGroup.add_argument('--problemId', help='Id of the problem to load its test set.')
    pCFLoadTestSet.add_argument('--transformer', help='A program that will be apply a transformation on each test case for instance to salvage what you can from multiple case test cases, it will receive each test case input and output seperated by --seperator and its supposed to print the same.')

    pLoadTest = p.add_parser('loadTestset', description='loads a non-CF problem test set from a file and stores it in db.')
    pLoadTest.add_argument('problemId', help='Id of the problem to load its test sets.')
    pLoadTest.add_argument('setPath', help='path of the set file to parse and load.')
    pLoadTest.add_argument('IOSeperator', help='The seperator of a single case input from output.')
    pLoadTest.add_argument('--testsSeperator', help='The seperator of different test cases.')

