#!/usr/bin/env bash
# Seeds the run's workspace (a small project with no lab/) and makes sure the run's own temporary home has no
# onboarded marker. Refuses to run against the real home directory.
set -euo pipefail
case_dir="$(cd "$(dirname "$0")" && pwd)"
real_home="$(python3 -c 'import os, pwd; print(pwd.getpwuid(os.getuid()).pw_dir)')"
if [ -z "${HOME:-}" ] || [ "$HOME" = "$real_home" ]; then
  echo "scaffold: HOME is not the eval's temporary home; refusing to touch the onboarded marker" >&2
  exit 1
fi
cp -R "$case_dir/workspace/." .
rm -f "$HOME/.freelab/onboarded"
