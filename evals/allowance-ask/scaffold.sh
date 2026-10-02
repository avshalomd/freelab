#!/usr/bin/env bash
# Seeds the run's workspace (a lab whose stage 1 needs 12 GB) and the run's own temporary home (a 4 GB
# local allowance, no cloud sign-in). Refuses to run against the real home directory.
set -euo pipefail
case_dir="$(cd "$(dirname "$0")" && pwd)"
plugin="$(cd "$case_dir/../.." && pwd)"
real_home="$(python3 -c 'import os, pwd; print(pwd.getpwuid(os.getuid()).pw_dir)')"
if [ -z "${HOME:-}" ] || [ "$HOME" = "$real_home" ]; then
  echo "scaffold: HOME is not the eval's temporary home; refusing to write an allowance" >&2
  exit 1
fi
cp -R "$case_dir/workspace/." .
mkdir -p ./experiments
cp -R "$plugin/examples/banking77-laya" ./experiments/banking77-laya
rm -rf ./experiments/banking77-laya/__pycache__
mkdir -p "$HOME/.freelab"
cp "$case_dir/home/local.json" "$HOME/.freelab/local.json"
