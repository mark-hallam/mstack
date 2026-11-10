"""Small file helpers shared by the setup commands: real paths, backups, and the mStack block in a Markdown file.

Python 3.9 or later, standard library only. Every setup changes the file a symbolic link points to, so these
helpers always work on the real path, and the preview names it.
"""
import os
import re
import shutil


START, END = "<!-- mstack:start -->", "<!-- mstack:end -->"
BLOCK_RE = re.compile(re.escape(START) + ".*?" + re.escape(END), re.S)


def real(path):
    return os.path.realpath(path)


def shown(path):
    """The path for a preview: when it is a symbolic link, also the real file that would change."""
    return path if real(path) == os.path.abspath(path) else "%s (a symbolic link: the file that would change is %s)" % (
        path, real(path))


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def keep_backup(path):
    """Copy an existing file to <file>.mstack-backup, unless the file already holds mStack's change and a backup of
    the file as it was before exists (so the backup stays the original)."""
    if not os.path.exists(path):
        return None
    backup = path + ".mstack-backup"
    if os.path.exists(backup) and "mstack" in (read(path) or "").lower():
        return backup
    shutil.copyfile(path, backup)
    return backup


def stable_copy():
    """Make sure the launcher in ~/.mstack/bin and install.json are current, so hooks keep working when a plugin
    update moves the original. Returns the launcher's path."""
    import install_state
    install_state.refresh()
    return install_state.launcher_path()


def add_block(text, block):
    """Put the block in: replace the one that is there, or append it so remove_block can take it out byte for byte."""
    if START in text:
        return BLOCK_RE.sub(lambda m: block, text)
    return (text + "\n" if text else "") + block + "\n"


def remove_block(text):
    """The text without mStack's block (and the one newline each side that add_block put there), or None if absent."""
    m = BLOCK_RE.search(text)
    if not m:
        return None
    before, after = text[:m.start()], text[m.end():]
    if after.startswith("\n"):
        after = after[1:]
    if before.endswith("\n"):
        before = before[:-1]
    return before + after


def write_or_delete(path, text):
    """Write the text back (keeping a backup), or delete the file when mStack created it and nothing else is in it
    (it has no backup, because a backup is only made of a file that was there first). Returns "written" or "deleted"."""
    if not text.strip() and not os.path.exists(path + ".mstack-backup"):
        os.remove(path)
        return "deleted"
    keep_backup(path)
    write(path, text)
    return "written"
