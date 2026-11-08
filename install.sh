#!/bin/sh
set -eu

usage() {
    echo "usage: install.sh <cortex|kiro> [--uninstall] [other harness-port flags]" >&2
    exit 2
}

case "${1:-}" in
cortex | kiro) target=$1 ;;
*) usage ;;
esac
shift

for tool in git uv; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "install.sh: '$tool' is not on PATH; install it first (the hooks run through uv)." >&2
        exit 1
    fi
done

repo=${HARNESS_REPO:-https://github.com/tfernd/harness}
dir=${HARNESS_HOME:-$HOME/.local/share/harness}

if [ -d "$dir/.git" ]; then
    if ! git -C "$dir" pull -q --ff-only; then
        echo "install.sh: could not update $dir (local changes or a diverged branch)." >&2
        echo "Fix or remove that clone by hand, then run this again; nothing was changed." >&2
        exit 1
    fi
elif [ -e "$dir" ]; then
    echo "install.sh: $dir exists and is not a git clone; move it away and run again." >&2
    exit 1
else
    git clone -q --depth 1 "$repo" "$dir"
fi

"$dir/bin/harness-port" --target "$target" "$@"

for arg in "$@"; do
    if [ "$arg" = "--uninstall" ]; then
        echo "Uninstalled. To remove the clone too, run: rm -rf \"$dir\""
    fi
done
