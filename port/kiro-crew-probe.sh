#!/bin/sh
set -eu

crew_file=${HARNESS_CREW_HOOKS:-$HOME/.kiro/crew/hooks.json}
marker=${HARNESS_CREW_MARKER:-$HOME/.kiro/crew/harness-probe.marker}

if [ ! -f "$crew_file" ]; then
    echo "kiro-crew-probe: $crew_file does not exist; open the Kiro crew once, then run this again." >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "kiro-crew-probe: python3 is needed to edit $crew_file." >&2
    exit 1
fi

edit() {
    HARNESS_PROBE_MODE=$1 HARNESS_PROBE_FILE=$crew_file HARNESS_PROBE_MARKER=$marker python3 - <<'PY'
import json, os, shutil

path = os.environ["HARNESS_PROBE_FILE"]
marker = os.environ["HARNESS_PROBE_MARKER"]
with open(path) as handle:
    document = json.load(handle)
entries = document.get("hooks", [])
if entries == {}:
    entries = []
entries = [entry for entry in entries if entry.get("name") != "harness-probe"]
if os.environ["HARNESS_PROBE_MODE"] == "add":
    shutil.copy2(path, path + ".harness-probe-backup")
    command = f"cat >/dev/null; echo fired >> '{marker}'; exit 0"
    entries.append(
        {
            "id": "b7e1c0de",
            "name": "harness-probe",
            "event": "PreToolUse",
            "matcher": "*",
            "matcher_mode": "glob",
            "command": command,
            "skills": [],
            "timeout": 30,
            "enabled": True,
            "last_run": 0.0,
            "last_status": "",
            "last_error": "",
            "run_count": 0,
        }
    )
document["hooks"] = entries
with open(path, "w") as handle:
    json.dump(document, handle, indent=2)
    handle.write("\n")
PY
}

rm -f "$marker"
edit add
trap 'edit remove' EXIT INT TERM

echo "Probe hook added to $crew_file."
echo "In a Kiro crew agent, ask it to run any one tool (for example: read a file)."
printf "Press Enter when it has run: "
read -r _answer

if [ -s "$marker" ]; then
    echo "PASS: the crew ran the probe hook. The harness entry shape works."
    status=0
else
    echo "FAIL: the marker did not appear. The crew did not run the entry; send the shape of a hook made in the dashboard (Agent Capabilities, Hooks) from $crew_file." >&2
    status=1
fi
edit remove
trap - EXIT INT TERM
rm -f "$marker"
echo "Probe hook removed."
exit "$status"
