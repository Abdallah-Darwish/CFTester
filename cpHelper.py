import argparse
from cgi import test
import dbMan
import tester

p = argparse.ArgumentParser()
pa = p.add_subparsers(dest='subparserName')
dbMan.addParser(pa)
tester.addParser(pa)
args = p.parse_args()
if dbMan.cmd(args) == False:
    tester.cmd(args)