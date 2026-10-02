#!/usr/bin/env bash
# freelab SessionStart hook: once per machine, add one line of context so the agent offers onboarding. After it
# has printed that line it writes the `nudged` marker and never prints again; it prints nothing once onboarded
# either. The user can still say "set up freelab" any time. Never reads any key or .env.
home="${FREELAB_HOME:-$HOME/.freelab}"
[ -f "$home/onboarded" ] && exit 0
[ -f "$home/nudged" ] && exit 0
mkdir -p "$home" 2>/dev/null && date +%Y-%m-%d > "$home/nudged" 2>/dev/null
cat <<'EOF'
freelab is not set up yet: early in this session, offer once to run the freelab onboard skill (it asks with AskUserQuestion and connects free GPU compute: Kaggle, Lightning AI, Modal). This line comes only this once on this machine; if the user says "Not now", do not raise it again (they can say "set up freelab" any time).
EOF
exit 0
