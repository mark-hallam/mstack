"""Shared --json behaviour for outcome.py: usage errors and crashes become one JSON object."""
import argparse
import json
import sys


class JsonParser(argparse.ArgumentParser):
    """An argparse parser whose usage errors become {"ok": false, "error": ...} when --json was given."""
    json_mode = False

    def error(self, message):
        if JsonParser.json_mode:
            raise SystemExit("%s: %s" % (self.prog, message))
        super().error(message)


def run_cli(ap, argv=None):
    """Parse and run. With --json, every error (a message, a usage mistake or a crash) is one JSON object
    {"ok": false, "error": ...} on standard output and the exit code is 1."""
    argv = sys.argv[1:] if argv is None else list(argv)
    JsonParser.json_mode = "--json" in argv
    try:
        args = ap.parse_args(argv)
        args.fn(args)
    except SystemExit as e:
        if JsonParser.json_mode and isinstance(e.code, str):
            print(json.dumps({"ok": False, "error": e.code}))
            sys.exit(1)
        raise
    except Exception as e:
        if not JsonParser.json_mode:
            raise
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}))
        sys.exit(1)
