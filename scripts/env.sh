#!/usr/bin/env bash
# freelab: write key placeholders into ./.env and check which keys are filled in, without ever printing a value.
#   scripts/env.sh add NAME...    create ./.env if missing (chmod 600), add a one-time comment and `NAME=` for each
#                                 name not yet defined (any `NAME=` line); prints `added NAME`; never edits a line
#   scripts/env.sh check NAME...  print `NAME: present` (non-empty value) or `NAME: missing`; exit 0 if all present
# Run it from the project root. It is a bash script, so it works the same when called from zsh.
set +xv  # first: under `bash -x` or `-v` the trace would print the values
MARKER='# freelab: paste each value after the =, no quotes, no spaces'

usage() {
  echo "usage: env.sh add NAME... | env.sh check NAME..." >&2
  exit 2
}

valid_name() {
  case "$1" in
    ''|[0-9]*|*[!A-Za-z0-9_]*) return 1 ;;
  esac
  return 0
}

defined() {  # NAME has a `NAME=` line (optionally after `export `)
  [ -f .env ] && grep -Eq "^[[:space:]]*(export[[:space:]]+)?$1=" .env
}

cmd="${1:-}"
[ "$#" -gt 0 ] && shift
[ "$#" -gt 0 ] || usage
for name in "$@"; do
  valid_name "$name" || { echo "env.sh: not a variable name: $name" >&2; exit 2; }
done

case "$cmd" in
  add)
    if [ ! -f .env ]; then
      (umask 077 && : > .env) || exit 1
    fi
    chmod 600 .env
    for name in "$@"; do
      defined "$name" && continue
      if [ -s .env ] && [ -n "$(tail -c 1 .env)" ]; then
        printf '\n' >> .env  # the last line had no newline
      fi
      grep -qxF "$MARKER" .env || printf '%s\n' "$MARKER" >> .env
      printf '%s=\n' "$name" >> .env
      echo "added $name"
    done
    ;;
  check)
    rc=0
    for name in "$@"; do
      value=""
      if [ -f .env ]; then
        line=$(grep -E "^[[:space:]]*(export[[:space:]]+)?$name=" .env | tail -n 1)
        value=${line#*=}
        value=$(printf '%s' "$value" | tr -d " \t\r\"'")
        case "$value" in \#*) value="" ;; esac
      fi
      if [ -n "$value" ]; then
        echo "$name: present"
      else
        echo "$name: missing"
        rc=1
      fi
      value=""
      line=""
    done
    exit "$rc"
    ;;
  *)
    usage
    ;;
esac
