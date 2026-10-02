#!/usr/bin/env bash
# Seeds the run's workspace (a small project that is not a freelab lab: no lab/, no .env) and the run's own
# temporary home (onboarded, so the session-start hook stays quiet and only the prompt can trigger freelab).
# Refuses to run against the real home directory.
set -euo pipefail
case_dir="$(cd "$(dirname "$0")" && pwd)"
real_home="$(python3 -c 'import os, pwd; print(pwd.getpwuid(os.getuid()).pw_dir)')"
if [ -z "${HOME:-}" ] || [ "$HOME" = "$real_home" ]; then
  echo "scaffold: HOME is not the eval's temporary home; refusing to write the onboarded marker" >&2
  exit 1
fi
cp -R "$case_dir/workspace/." .
mkdir -p "$HOME/.freelab"
printf '%s\n' '{"date":"2026-10-01","machine":{"day":"low","night":"full"},"services":[],"checks":{}}' \
  > "$HOME/.freelab/onboarded"
