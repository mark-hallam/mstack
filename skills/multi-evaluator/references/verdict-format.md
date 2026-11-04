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
 "broken": ["anything that errored, did nothing, or showed wrong data"]}
```

| Field | Rule |
|---|---|
| `reviewer`, `round` | Must match the reviewer and round being saved (filled in if left out). |
| `journeys` | Every journey in the config, each with `id`, `score` and `if_fixed`. |
| `score` | 0 to 10. A 10 means the reviewer could not find anything to improve, against every criterion in force. |
| `if_fixed` | 0 to 10: the score this journey would get if this reviewer's fixes for it were made. |
| `fixes` | Each with `severity` (`high`, `medium` or `low`), `where`, `problem` and `fix`. |
| `overall` | 0 to 10. |
| `top_fixes` | The five changes that would raise the scores most. |
| `broken` | Anything that errored, did nothing, or showed wrong data. |

A reply wrapped in prose or a fenced code block is fine: the tool finds the JSON inside it.
