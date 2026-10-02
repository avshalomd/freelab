#!/usr/bin/env bash
# Seeds the run's workspace: a lab with two finished local runs (full-a, full-b, the best) and one still running
# (full-c), the quick-start experiment, and, made here because git ignores them, a __pycache__ folder and small
# dummy checkpoint files (a few KB each, named like the real ones), plus an unfinished checkpoint write in full-a.
# Writes the run's own temporary home (onboarded, no cloud). Refuses to run against the real home directory.
set -euo pipefail
case_dir="$(cd "$(dirname "$0")" && pwd)"
plugin="$(cd "$case_dir/../.." && pwd)"
real_home="$(python3 -c 'import os, pwd; print(pwd.getpwuid(os.getuid()).pw_dir)')"
if [ -z "${HOME:-}" ] || [ "$HOME" = "$real_home" ]; then
  echo "scaffold: HOME is not the eval's temporary home; refusing to write the onboarded marker" >&2
  exit 1
fi
cp -R "$case_dir/workspace/." .
mkdir -p ./experiments
cp -R "$plugin/examples/banking77-laya" ./experiments/banking77-laya
rm -rf ./experiments/banking77-laya/__pycache__
mkdir -p ./experiments/banking77-laya/__pycache__
head -c 4096 /dev/zero > ./experiments/banking77-laya/__pycache__/data.cpython-312.pyc
head -c 4096 /dev/zero > ./experiments/banking77-laya/__pycache__/laya_head.cpython-312.pyc
ckpt() {  # ckpt RUN STEP: a complete dummy checkpoint
  local d="lab/runs/$1/ckpt/step-$2"
  mkdir -p "$d"
  head -c 8192 /dev/zero > "$d/state.pt"
  printf '{"step": %d}\n' "$((10#$2))" > "$d/meta.json"
  : > "$d/COMPLETE"
}
ckpt full-a 00000145
ckpt full-a 00000290
ckpt full-b 00000145
ckpt full-b 00000290
ckpt full-c 00000100
mkdir -p lab/runs/full-a/ckpt/.tmp-step-00000290
head -c 2048 /dev/zero > lab/runs/full-a/ckpt/.tmp-step-00000290/state.pt
mkdir -p "$HOME/.freelab"
printf '%s\n' '{"date":"2026-10-01","machine":{"day":"medium","night":"full"},"services":[],"checks":{}}' \
  > "$HOME/.freelab/onboarded"
