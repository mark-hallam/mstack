#!/usr/bin/env python3
"""A stand-in reviewer for the self-test: no AI and no network beyond this computer.

It reads its brief on standard input the way a real reviewer would, starts its own copy of the product
with the brief's serve command, drives one journey with the brief's journey driver, and replies with a
verdict in the brief's reply format. Its scores are fixed per round so the report has a trend to show:
they are illustrative, not a review.

  python3 stand_in_reviewer.py --id stand-in --round 1 --work <folder>   (brief on standard input)
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time

SCORES = {1: (4, 5), 2: (7, 8), 3: (9, 10)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--offset", type=int, default=0)
    args = ap.parse_args()
    brief = sys.stdin.read()
    serve = re.search(r"`(python3 \S+ serve --dir \S+ --port \d+)`", brief).group(1)
    driver = shlex.split(re.search(r"`node (\S+) <steps.json>", brief).group(1))[0]
    jids = [int(m) for m in re.findall(r"^(\d+)\. \*\*", brief, re.M)]
    cmd = shlex.split(serve)
    cmd[0] = sys.executable
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        line = proc.stdout.readline()
        url = re.search(r"ready: (\S+)", line).group(1)
        steps = {"viewport": {"w": 1440, "h": 1000}, "steps": [{"do": "goto", "url": url, "ms": 600}, {"do": "click", "text": "Add"}]}
        os.makedirs(args.work, exist_ok=True)
        path = os.path.join(args.work, "journey-1.json")
        with open(path, "w") as fh:
            json.dump(steps, fh)
        subprocess.run(["node", driver, path, os.path.join(args.work, "journey-1")], check=True, capture_output=True)
        with open(os.path.join(args.work, "journey-1", "log.txt")) as fh:
            log = fh.read()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        time.sleep(0.2)
    clicked = "clicked button" in log
    score, if_fixed = SCORES.get(args.round, (9, 10))
    score = max(0, min(10, score + args.offset))
    if "id `control`" in brief:                      # the frozen control: a score that wobbles by one, like a real judge
        jids.append("control")
    journeys = [{"id": j, "name": "Journey %s" % j, "score": (6 + args.round % 2) if j == "control" else score,
                 "if_fixed": (6 + args.round % 2) if j == "control" else if_fixed,
                 "what_worked": ["The add button was found and pressed." if clicked else "The page opened."],
                 "fixes": [] if (score >= 9 or j == "control") else [{"severity": "high" if score < 6 else "medium", "where": "Home",
                                                  "problem": "Stand-in problem for round %d." % args.round,
                                                  "fix": "Stand-in fix for round %d." % args.round}]} for j in jids]
    print("Here is my verdict.\n```json\n%s\n```" % json.dumps({
        "reviewer": args.id, "round": args.round, "journeys": journeys, "overall": score,
        "top_fixes": ["Stand-in proposal: make the main action clearer."] if score < 9 else [],
        "broken": [] if clicked else ["The add button was not found."]}, indent=1))


if __name__ == "__main__":
    main()
