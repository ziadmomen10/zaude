"""
zhook.py — the stable hook launcher [D16]. settings.json calls a SHORT, fixed command:

    python "<kernel>/zhook.py" pre_tool_use

instead of long inlined logic. This sidesteps Windows argv-length + quoting problems once
paths contain spaces. It dispatches to the right hook module, passing stdin through.

The launcher itself is wrapped so that ANY failure to even locate/import the hook fails
OPEN (exit 0) — it must never be the thing that blocks a tool call.
"""
import os
import sys

EVENTS = {
    "pre_tool_use": "hooks.pre_tool_use",
    "user_prompt_submit": "hooks.user_prompt_submit",  # Zaude 3 P0: always-on intent front door
    # post_tool_use / session_start / session_end land here in Phase 2.
}


def main():
    try:
        event = sys.argv[1] if len(sys.argv) > 1 else ""
        mod = EVENTS.get(event)
        if not mod:
            sys.exit(0)  # unknown event -> no-op
        vroot = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, vroot)
        __import__(mod)
        sys.modules[mod].main()
    except SystemExit:
        raise
    except Exception:
        # Launcher-level failure must never block a tool. Fail open.
        sys.exit(0)


if __name__ == "__main__":
    main()
