#!/usr/bin/env python3
"""
Stable Zaude HOOK launcher. Resolves the CURRENT kernel and dispatches to its zhook.py. Used by
settings.json so the wired hook is version-independent. FAILS OPEN (exit 0) on any problem — the
hook must never be the thing that blocks a tool call when the kernel can't be located.
"""
import os
import sys
import runpy

HOME = os.path.expanduser("~")


def main():
    try:
        with open(os.path.join(HOME, ".zaude", "kernel", "CURRENT"), "r", encoding="utf-8") as f:
            ver = f.read().strip()
        z = os.path.join(HOME, ".zaude", "kernel", "versions", ver, "zhook.py")
        if not os.path.isfile(z):
            sys.exit(0)
        runpy.run_path(z, run_name="__main__")
    except SystemExit:
        # The kernel hook signals DENY via stdout JSON (exit 0); a non-zero exit must NEVER leak
        # out of the launcher and accidentally block a tool. Force fail-open. [codex-CRITICAL]
        sys.exit(0)
    except Exception:
        sys.exit(0)  # fail open


if __name__ == "__main__":
    main()
