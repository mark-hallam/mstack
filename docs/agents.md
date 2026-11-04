# mStack: instructions for any AI agent

You have been pointed at this page by a person who wants to use one of the skills in mStack
(https://github.com/mark-hallam/mstack). Follow these steps. They work from any agent that can read web
pages and run commands on the person's computer: Claude, Codex, Cursor, ChatGPT with a terminal, Gemini
and others.

## 1. Get the skills

```
git clone https://github.com/mark-hallam/mstack.git ~/mstack
```

(If you cannot run commands, read the files on GitHub and tell the person which commands to run.)

Needs Python 3.9 or later, Node.js 18 or later and Google Chrome or Chromium. Nothing else.

## 2. Pick the skill

| Skill | Use it when |
|---|---|
| multi-evaluator | The person wants their site, app or document reviewed and improved in rounds until every user journey scores 10 out of 10 from at least two independent AI reviewers from different makers, with before and after screenshots and an HTML report each round. |

## 3. Follow it

Read `~/mstack/skills/<skill>/SKILL.md` in full and follow it step by step. In short, for multi-evaluator:

1. Agree the journeys (real tasks, end to end) and the criteria with the person.
2. `python3 ~/mstack/skills/multi-evaluator/scripts/eval_loop.py init --dir design-review --start "<start command with {port}>"`,
   then fill in `design-review/mstack-eval.json`.
3. Each round: `start-round`, `capture`, `brief`, then run every reviewer in fresh context with its brief
   (`review` runs command line reviewers such as Codex; you start agent reviewers yourself), save each
   reply with `verdict`, and build the report with `report`.
4. Show the person `design-review/report.html`. Fix what the reviewers found, then repeat until
   `status` says every reviewer gives every journey 10. Then real people test it, and they win any
   disagreement.

At any point, `eval_loop.py status --dir design-review --json` tells you where the loop is and what to do next.

## Ground rules

- Act only with the person's permission. Never submit real payments, messages or personal data while
  reviewing; use demo data.
- Reviewers never see each other's verdicts or earlier scores.
- Tell the person plainly what you did, what passed, and what you could not check.
