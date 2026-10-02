#!/usr/bin/env bash
# Seeds the run's workspace (a finished Modal connection check and its ledger lines) and the run's own temporary
# home (this machine's allowance, set with presets; no onboarded marker yet, since onboarding is under way).
# Refuses to run against the real home directory.
set -euo pipefail
case_dir="$(cd "$(dirname "$0")" && pwd)"
real_home="$(python3 -c 'import os, pwd; print(pwd.getpwuid(os.getuid()).pw_dir)')"
if [ -z "${HOME:-}" ] || [ "$HOME" = "$real_home" ]; then
  echo "scaffold: HOME is not the eval's temporary home; refusing to write an allowance" >&2
  exit 1
fi
cp -R "$case_dir/workspace/." .
mkdir -p "$HOME/.freelab"
cp "$case_dir/home/local.json" "$HOME/.freelab/local.json"
