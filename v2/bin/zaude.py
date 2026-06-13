#!/usr/bin/env python3
"""
Stable Zaude launcher. Resolves the CURRENT kernel version and dispatches to its cli.py, so slash
commands / scripts call a VERSION-INDEPENDENT path:  python ~/.zaude/bin/zaude.py <command> ...
"""
import os
import sys
import runpy

HOME = os.path.expanduser("~")


def main():
    try:
        with open(os.path.join(HOME, ".zaude", "kernel", "CURRENT"), "r", encoding="utf-8") as f:
            ver = f.read().strip()
    except Exception:
        sys.stderr.write("zaude: no kernel CURRENT pointer at ~/.zaude/kernel/CURRENT\n")
        sys.exit(1)
    cli = os.path.join(HOME, ".zaude", "kernel", "versions", ver, "cli.py")
    if not os.path.isfile(cli):
        sys.stderr.write("zaude: kernel %s not installed (%s)\n" % (ver, cli))
        sys.exit(1)
    # cli.py parses sys.argv[1:]; leave argv as-is and run its __main__.
    runpy.run_path(cli, run_name="__main__")


if __name__ == "__main__":
    main()
