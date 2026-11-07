#!/usr/bin/env python3
"""Run every test: the leak scan, the packaging checks, and each skill's self-test.

  python3 tests/run_all.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = ["leak_scan.py", "test_skills.py", "test_mstack.py", "test_outcome.py", "test_away.py", "test_crew.py", "test_crew_branch.py", "test_readiness_per_round.py", "selftest.py"]

failed = []
for t in TESTS:
    print("\n==== %s" % t, flush=True)
    if subprocess.run([sys.executable, os.path.join(HERE, t)]).returncode != 0:
        failed.append(t)
print("\n%s" % ("every test passed" if not failed else "failed: " + ", ".join(failed)))
sys.exit(1 if failed else 0)
