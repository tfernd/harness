#!/usr/bin/env -S python3 -I
"""SessionStart and SubagentStart hook: in a project with `.harness.json`, tells a session what it owes.

SessionStart tells the main session to load `harness:orchestrator`. SubagentStart tells a role the report gate judges
which report form it owes. Any other agent type gets nothing. The text reaches the model as `additionalContext`.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import find_project, get_report_form  # noqa: E402

SESSION_TEXT = "This project runs under the harness plugin. Load the `harness:orchestrator` skill before anything else."
FORM_TEXTS = {
    "full": "End with the full form of the `harness:report` skill: the ten sections, from Answer to FEEDBACK FOR THE "
    "ORCHESTRATOR. A hook sends back a report that breaks the form.",
    "short": "End with the short form of the `harness:report` skill: Answer, Work, NOT CHECKED, PROBLEMS MET, REPORT CARD. "
    "A hook sends back a report that breaks the form.",
}


def main() -> int:
    event = json.load(sys.stdin)
    root, config = find_project(event.get("cwd") or os.getcwd())
    if root is None:
        return 0
    name = event.get("hook_event_name")
    text = ""
    if name == "SessionStart":
        text = SESSION_TEXT
    elif name == "SubagentStart":
        form = get_report_form(event.get("agent_type") or "", config.get("report", {}))
        text = FORM_TEXTS.get(form, "")
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}}))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in a context hook must not stop a session
        print(f"the harness context hook failed: {error!r}", file=sys.stderr)
        sys.exit(1)
