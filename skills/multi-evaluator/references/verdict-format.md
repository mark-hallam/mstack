# The reviewer's reply format

Every reviewer replies with JSON only. `eval_loop.py verdict` and `eval_loop.py validate` check it.

```json
{"reviewer": "codex", "round": 2,
 "journeys": [
   {"id": 1, "name": "Clear the day", "score": 6, "if_fixed": 9,
    "what_worked": ["The list puts what is overdue first."],
    "fixes": [{"severity": "high", "where": "Today, progress counter",
               "problem": "Recording a follow-up as sent does not raise the cleared count.",
               "fix": "Count recorded follow-ups as cleared."}]}],
 "overall": 7,
 "top_fixes": ["Count recorded follow-ups as cleared.", "..."],
 "broken": ["anything that errored, did nothing, or showed wrong data"],
 "could_not_test": ["Payments: needs a real card"],
 "did_not_touch": ["Deleting the account"]}
```

| Field | Rule |
|---|---|
| `reviewer`, `round` | Must match the reviewer and round being saved (filled in if left out). |
| `journeys` | Every journey in the config, each with `id`, `score` and `if_fixed`. |
| `score` | 0 to 10. A 10 means the reviewer could not find anything to improve, against every criterion in force, so a 10 with fixes is refused. 9 or better from everyone, agreeing within a point, is the bar for "ready for people". |
| `if_fixed` | 0 to 10: the score this journey would get if this reviewer's fixes for it were made. Required, and never below `score`. |
| `fixes` | Each with `severity` (`blocker`, `high`, `medium` or `low`), `where`, `problem` and `fix`. A **blocker** stops the person finishing the journey, or breaks a safety or trust rule; a journey with a blocker cannot score above 5, and a round with an open blocker is never ready. |
| `overall` | 0 to 10. |
| `top_fixes` | The five changes that would raise the scores most. |
| `broken` | Anything that errored, did nothing, or showed wrong data. |
| `could_not_test` | Optional list: what the reviewer could not reach or try, and why. Shown in the report. |
| `did_not_touch` | Optional list: anything deliberately avoided, for example payments. Shown in the report. |

## The comparison reply (from round 2)

```json
{"reviewer": "codex", "round": 2,
 "compare": {"improved": ["..."], "regressed": ["..."], "unchanged": ["..."], "note": "one sentence"},
 "regrade": [{"id": "f1", "state": "done", "seen": "The button now reads Add book"}]}
```

`regrade` answers every numbered fix in the compare brief (at most 12). `state` is `done`, `partly`, `not`,
`regressed` or `not_testable`; `seen` quotes the exact words or state on screen. `verdict --compare` refuses
a reply that leaves an id out, naming the missing ones.

A reply wrapped in prose or a fenced code block is fine: the tool finds the JSON inside it.
