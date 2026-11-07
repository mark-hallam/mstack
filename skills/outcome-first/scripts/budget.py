"""The question budget for outcome.py: which open questions to ask, and which are taken by default.

Python 3.9 or later, standard library only. Used by `outcome.py questions`.
"""
import json

DEFAULT_CAP = 6


def config(path):
    """The shared ~/.mstack/config.json (or $MSTACK_HOME/config.json) as a dict; empty when missing or broken."""
    try:
        with open(path, encoding="utf-8") as fh:
            return dict(json.load(fh))
    except (OSError, ValueError, TypeError):
        return {}


def cap_from(path):
    """max_questions from the shared config, or 6 when it is missing or not a whole number above zero."""
    cap = config(path).get("max_questions", DEFAULT_CAP)
    return cap if isinstance(cap, int) and not isinstance(cap, bool) and cap > 0 else DEFAULT_CAP


def split(open_qs, cap):
    """(ask, by_default). Questions without a default are always asked, then defaulted ones fill the cap."""
    nodef = [q for q in open_qs if not q.get("default")]
    ask = nodef + [q for q in open_qs if q.get("default")][:max(0, cap - len(nodef))]
    return ask, [q for q in open_qs if q not in ask]


def render(ask, rest, cap):
    line = lambda q: "%s. %s%s" % (q["id"], q["text"], " (default: %s)" % q["default"] if q.get("default") else "")
    text = "\n".join(line(q) for q in ask) or "No open questions."
    over = len([q for q in ask if not q.get("default")])
    if over > cap:
        text += "\n(%d questions have no default, more than the cap of %d, so all are asked.)" % (over, cap)
    if rest:
        text += "\nTaken by default unless you say otherwise:\n" + "\n".join(line(q) for q in rest)
    return text
