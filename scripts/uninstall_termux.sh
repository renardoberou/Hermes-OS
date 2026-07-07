#!/bin/sh
# uninstall_termux.sh — remove what install_termux.sh created, nothing else.
#
#   ./scripts/uninstall_termux.sh                # remove the wrapper only
#   ./scripts/uninstall_termux.sh --purge-state  # also remove approvals/state
#
# The repo folder itself is never deleted (that's your call), and no
# Hermes cron/gateway/profile state is ever touched.
set -eu

MARKER="# hermes-android-agentic-os wrapper v1"
TARGET="${HOME}/.local/bin/hermes-os"
STATE_DIR="${HERMES_OS_STATE_DIR:-${HERMES_OS_HERMES_HOME:-${HOME}/.hermes}/state/hermes-android-agentic-os}"

if [ -e "$TARGET" ]; then
  if grep -q "$MARKER" "$TARGET" 2>/dev/null; then
    rm -f "$TARGET"
    echo "ok:   removed $TARGET"
  else
    echo "skip: $TARGET exists but was not created by this installer — left in place"
  fi
else
  echo "skip: $TARGET not present"
fi

if [ "${1:-}" = "--purge-state" ]; then
  if [ -d "$STATE_DIR" ]; then
    rm -rf "$STATE_DIR"
    echo "ok:   removed state dir $STATE_DIR (approval queue included)"
  else
    echo "skip: no state dir at $STATE_DIR"
  fi
else
  echo "note: state dir kept at $STATE_DIR (use --purge-state to remove)"
fi

echo "done. The repo folder itself was not touched."
