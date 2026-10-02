#!/usr/bin/env python3
"""freelab PreToolUse guard (all tools). Only in a project that uses freelab (hooklib.uses_freelab on the hook's
cwd); anywhere else it exits 0 with no output. Even there, rules 2 and 3 cover only freelab's own launches and
cloud storage: the rest of the project and the session is the user's other work, and the guard says nothing.

1. Secrets: never show a key. Denies reading or editing `.env` (any directory), ~/.modal.toml, ~/.kaggle/**,
   ~/.lightning/** with the file tools, and shell commands (Bash, and a few PowerShell forms) that would print them
   or the environment: readers, greps (a recursive one, or a Grep content search, whose pattern could match a key
   line in a .env it would reach), and interpreter code (`python -c`, `node -e`, `perl -e`, `ruby -e`, awk, or a
   heredoc fed to an interpreter) that outputs the whole environment or a key. Text inside `$(...)` and backticks,
   `bash -c` strings and wrapped commands (`sudo`, `nice`, `timeout`, `xargs`, ...) are checked too; a heredoc fed
   to anything else (`cat > notes.md <<EOF`, a `git commit -m "$(cat <<EOF ...)"` message) is plain text and is
   not looked at. No rules on git commands. Allows scripts/withenv, scripts/env.sh add|check, sourcing .env into a
   command's environment, appending to .env, `grep -q`, `open -t .env`, and code that reads one named variable
   that is not a key.
2. Cloud deletes of freelab's storage (freelab_delete): `ask` for `modal volume rm freelab-runs ...`, Kaggle
   kernel or dataset deletes of a `freelab-...` slug, and Lightning deletes of freelab's Studio, its
   `freelab-runs/` and `freelab-init/` folders or a job that is one of freelab's runs; deny
   `modal volume delete freelab-runs` (it deletes every run on the Volume). Other deletes: no output.
3. Launch gate for freelab's own launches (freelab_launch): `modal run` of lab/backends/modal_app.py, `kaggle
   kernels push` of a kernel folder under lab/backends/ (or whose kernel-metadata.json names a `freelab-` kernel),
   `lightning job run` on the `freelab` Studio or writing to `freelab-runs`, and the plugin's
   scripts/backends/local_run.py. A non-smoke one needs a numeric Target and a Budget in lab/charter.md, a cost
   estimate in lab/ledger.jsonl newer than the last gated launch, and for Modal, Lightning and local runs a
   minutes cap, all looked for in the launch's own command segment. hooks/post.py (PostToolUse) records each such
   launch that succeeded in lab/.launches. A smoke run (`--smoke`, a `smoke-<backend>` run id) and `--help`/`-h`
   in the same segment are exempt from the gate, and `--help` from the delete ask. The user's own `modal run
   app.py`, `kaggle kernels push -p mykernel` or Lightning jobs get no output.

An accident guard, not a sandbox: clear rules over exhaustive parsing. Any error allows the call (exit 0)."""
from __future__ import annotations
import fnmatch, json, os, re, shlex, sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ inside the installed plugin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooklib import hook_cwd, uses_freelab, read_input  # noqa: E402

KEY_NAMES = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "KAGGLE_API_TOKEN", "KAGGLE_KEY", "LIGHTNING_API_KEY",
             "LIGHTNING_USER_ID")
KEY_REF = re.compile(r"\$\{?(?:%s)\b" % "|".join(KEY_NAMES))
KEY_WORD = re.compile(r"\b(?:%s)\b" % "|".join(KEY_NAMES))
SECRET_TOKEN = re.compile(r"(?:^|/)\.env(?:[*?\[].*)?$|(?:^|/)\.modal\.toml$|(?:^|/)\.kaggle(?:/|$)"
                          r"|(?:^|/)\.lightning(?:/|$)")
SECRET_IN_CODE = re.compile(r"(?<![\w.])\.env(?![\w.-])|\.modal\.toml|\.kaggle/|\.lightning/")

READERS = {"cat", "head", "tail", "less", "more", "bat", "batcat", "nl", "od", "xxd", "strings", "hexdump", "tac",
           "base64", "sort", "uniq", "cut", "paste", "diff", "cmp", "column", "fold", "rev", "tee", "zcat", "pr"}
COPIERS = {"cp", "mv", "rsync", "scp", "install", "dd"}
GREPS = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "zgrep"}
EDITORS = {"sed", "awk", "gawk", "mawk", "nawk", "perl", "ruby", "python", "python3", "node", "deno", "bun", "php"}
INTERPRETERS = {"perl", "ruby", "python", "python3", "node", "deno", "bun", "php"}
AWKS = {"awk", "gawk", "mawk", "nawk"}
# Commands that run the command after them, with the options of each that take a value (`sudo -u me cat .env`).
WRAPPERS = {"sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"}, "doas": {"-u", "-C"},
            "command": set(), "builtin": set(), "exec": {"-a"}, "time": {"-f", "-o"}, "nohup": set(),
            "nice": {"-n"}, "ionice": {"-c", "-n", "-p"}, "stdbuf": {"-i", "-o", "-e"}, "withenv": set(),
            "timeout": {"-s", "-k", "--signal", "--kill-after"},
            "xargs": {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a"}}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
SEPARATORS = {";", "&&", "||", "|", "&", "|&", ";;", "(", ")", "{", "}"}
REDIRECTS = {"<", ">", ">>", "<<", "<<<", "&>", "&>>", ">&", "<&", ">|", "<>"}

PLUGIN_ENV = "`${CLAUDE_PLUGIN_ROOT}/scripts/env.sh check NAME`"
READ_REASON = ("freelab never shows key values, so {what} is blocked. To see whether a key is set, run "
               + PLUGIN_ENV + " (it prints present or missing). To fill a key in, ask the user to open .env in "
               "their own editor (`open -t .env` on macOS, `xdg-open .env` on Linux).")
EDIT_REASON = ("freelab never edits .env with Edit or Write (that would put the values on screen). Add an empty "
               "placeholder with `${CLAUDE_PLUGIN_ROOT}/scripts/env.sh add NAME`, and ask the user to paste the value "
               "in their own editor (`open -t .env` on macOS, `xdg-open .env` on Linux).")
TRUNCATE_REASON = ("this would overwrite .env and erase the keys in it. Add placeholders with "
                   "`${CLAUDE_PLUGIN_ROOT}/scripts/env.sh add NAME` (it only appends).")
DUMP_REASON = ("this command would print environment values, which can include API keys. Check a key with "
               + PLUGIN_ENV + "; run a command with the keys loaded with `${CLAUDE_PLUGIN_ROOT}/scripts/withenv CMD`.")
CRED_REASON = ("this command prints a credential. freelab never shows key values: check a key with "
               + PLUGIN_ENV + ", and test a connection with the backend's smoke run instead.")
VOLUME_DELETE_REASON = ("`modal volume delete` deletes the whole Volume, every run on it included (running ones "
                        "too); freelab never needs it. Remove one run's folder with `modal volume rm -r freelab-runs "
                        "ID/ckpt` instead (the cleanup skill).")
ASK_DELETE_REASON = ("This permanently deletes {what}; there is no trash. Approve only if you want it "
                     "deleted.")


# --- output -------------------------------------------------------------------------------------------------------


def decide(decision: str, reason: str) -> None:
    """A deny reason goes to Claude, so it names the guard; an ask reason is shown to the user as it is."""
    text = reason if decision == "ask" else "freelab guard: " + reason
    # The agent's Bash has no CLAUDE_PLUGIN_ROOT, so name the real folder in the commands the reason suggests.
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(Path(__file__).resolve().parent.parent)
    text = text.replace("${CLAUDE_PLUGIN_ROOT}", root)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                             "permissionDecisionReason": text}}))


# --- searches that could print a key's line ----------------------------------------------------------------------


def key_line_match(pattern: str, icase: bool = False, fixed: bool = False) -> bool:
    """True when a search for `pattern` would match a key's line in .env (`KAGGLE_KEY=...`): `KAGGLE`,
    `MODAL_TOKEN_.*`, `=` and `.` do; `def main` and a lowercase `kaggle` (without -i) do not. A pattern Python
    cannot compile is taken as a literal string."""
    for name in KEY_NAMES:
        line = name + "="
        if not fixed:
            try:
                if re.search(pattern, line, re.I if icase else 0):
                    return True
                continue
            except re.error:
                pass
        if (pattern.lower() in line.lower()) if icase else (pattern in line):
            return True
    return False


def _bre_to_python(pattern: str) -> str:
    r"""A grep basic regex (`a\|b`, `\(x\)`) as a Python one: there `\|` `\(` ... are the operators and a bare
    `|` `(` ... is a literal."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            n = pattern[i + 1]
            out.append(n if n in "|(){}+?" else c + n)
            i += 2
            continue
        out.append("\\" + c if c in "|(){}+?" else c)
        i += 1
    return "".join(out)


GREP_VALUE_OPTS = {"-e", "-f", "-m", "-A", "-B", "-C", "-d", "-D", "--regexp", "--file", "--max-count", "--context",
                   "--after-context", "--before-context", "--include", "--exclude", "--exclude-dir", "--exclude-from",
                   "--directories", "--devices", "--label", "--binary-files"}
RG_VALUE_OPTS = {"-e", "-f", "-g", "-t", "-T", "-m", "-A", "-B", "-C", "-M", "-j", "-E", "-r", "-G", "--regexp",
                 "--file", "--glob", "--iglob", "--type", "--type-not", "--max-count", "--context", "--after-context",
                 "--before-context", "--max-columns", "--threads", "--encoding", "--replace", "--max-depth",
                 "--ignore-file", "--type-add", "--pre", "--file-search-regex", "--ignore", "--ignore-dir", "--depth"}


def _grep_parts(cmd: str, args: list[str]):
    """(patterns or None when they come from a file, [(option, value)], paths) of a grep, rg or ag command."""
    value_opts = GREP_VALUE_OPTS if cmd in ("grep", "egrep", "fgrep", "zgrep") else RG_VALUE_OPTS
    opts, positional, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            positional += args[i + 1:]
            break
        if a.startswith("--"):
            name, eq, val = a.partition("=")
            if not eq and name in value_opts and i + 1 < len(args):
                val, i = args[i + 1], i + 1
            opts.append((name, val))
        elif a.startswith("-") and len(a) > 1:
            for k, ch in enumerate(a[1:], 1):
                if "-" + ch in value_opts:
                    val = a[k + 1:]
                    if not val and i + 1 < len(args):
                        val, i = args[i + 1], i + 1
                    opts.append(("-" + ch, val))
                    break
                opts.append(("-" + ch, ""))
        else:
            positional.append(a)
        i += 1
    names = [n for n, _ in opts]
    patterns = [v for n, v in opts if n in ("-e", "--regexp")]
    if not patterns:
        if "-f" in names or "--file" in names:
            return None, opts, positional
        patterns, positional = positional[:1], positional[1:]
    return patterns, opts, positional


def grep_leak(cmd: str, args: list[str]) -> bool:
    """True for a recursive grep (`grep -r`, `rg`/`ag` with hidden files) that would print a key's line of a .env
    it reaches: its pattern matches one (key_line_match) and no --exclude/--include, -g glob or -t type leaves .env
    out. rg and ag skip hidden files such as .env unless told (--hidden, -uu, -.)."""
    patterns, opts, _ = _grep_parts(cmd, args)
    names = [n for n, _ in opts]
    if cmd in ("rg", "ag"):
        recursive = "--hidden" in names or "-." in names or names.count("-u") + names.count("--unrestricted") >= (
            2 if cmd == "rg" else 1)
    else:
        recursive = bool({"-r", "-R", "--recursive", "--dereference-recursive"} & set(names)) or \
            any(n in ("-d", "--directories") and v == "recurse" for n, v in opts)
    if not recursive:
        return False
    includes = [v for n, v in opts if n in ("--include", "-g", "--glob", "--iglob") and not v.startswith("!")]
    excludes = [v.lstrip("!") for n, v in opts if n in ("--exclude",) or (n in ("-g", "--glob", "--iglob")
                                                                           and v.startswith("!"))]
    if any(fnmatch.fnmatch(".env", g) for g in excludes) or "-t" in names or "--type" in names or (
            includes and not any(fnmatch.fnmatch(".env", g) for g in includes)):
        return False
    if patterns is None:
        return True
    icase = cmd == "ag" or bool({"-i", "-y", "--ignore-case", "-S", "--smart-case"} & set(names))
    fixed = cmd == "fgrep" or bool({"-F", "--fixed-strings", "-Q", "--literal"} & set(names))
    bre = cmd in ("grep", "zgrep") and not ({"-E", "-P", "--extended-regexp", "--perl-regexp"} & set(names))
    return any(key_line_match(_bre_to_python(p) if bre and not fixed else p, icase, fixed) for p in patterns)


# --- file tools ---------------------------------------------------------------------------------------------------


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def secret_file(path: str, cwd: str) -> str | None:
    """What the path is, when it is a protected file or folder, else None."""
    if not isinstance(path, str) or not path:
        return None
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = Path(cwd) / p
    p = Path(os.path.normpath(str(p)))
    if p.name == ".env":
        return ".env"
    home = Path(os.path.normpath(str(_home())))
    for rel, label in ((".modal.toml", "~/.modal.toml"), (".kaggle", "~/.kaggle"), (".lightning", "~/.lightning")):
        target = home / rel
        if p == target or target in p.parents:
            return label
    return None


def _plain_file(path, cwd: str) -> bool:
    """True when `path` is one existing regular file (secret_file has already said it is not a key file): a
    content search there cannot reach .env. A folder could hold a .env at any depth, so it does not count."""
    if not isinstance(path, str) or not path:
        return False
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = Path(cwd) / p
    try:
        return p.is_file()
    except OSError:
        return False


def check_file_tool(tool: str, ti: dict, cwd: str):
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        what = secret_file(ti.get("file_path") or ti.get("notebook_path"), cwd)
        if what == ".env":
            return "deny", EDIT_REASON
        if what:
            return "deny", READ_REASON.replace("{what}", f"editing {what}")
        return None
    if tool in ("Read", "NotebookRead"):
        what = secret_file(ti.get("file_path") or ti.get("notebook_path"), cwd)
        if what:
            return "deny", READ_REASON.replace("{what}", f"reading {what}")
        return None
    if tool == "Grep":
        path, glob = ti.get("path"), ti.get("glob")
        what = secret_file(path, cwd)
        last = glob.replace("\\", "/").rsplit("/", 1)[-1] if isinstance(glob, str) and glob else ""
        if not what and last:   # a glob aimed at a key file (`.env*`), not one that also takes every file (`*`)
            named = [n for n in (".env", ".modal.toml", "kaggle.json") if fnmatch.fnmatch(n, last)]
            if named and not any(fnmatch.fnmatch(g, last) for g in ("x", "x.py", "x.md", "x.json", "x.toml")):
                what = named[0]
        if what:
            return "deny", READ_REASON.replace("{what}", f"searching inside {what}")
        reaches_env = not ti.get("type") and not _plain_file(path, cwd) and (not last or fnmatch.fnmatch(".env", last))
        if ti.get("output_mode") == "content" and reaches_env \
                and key_line_match(str(ti.get("pattern", "")), icase=bool(ti.get("-i"))):
            return "deny", READ_REASON.replace("{what}", "a content search whose pattern matches a key's line in a "
                                               ".env it could reach (give a `glob` or `type` that leaves .env out, "
                                               "a single file as `path`, or use output_mode files_with_matches)")
        return None
    if tool == "Glob":
        what = secret_file(ti.get("path"), cwd)
        pattern = str(ti.get("pattern", ""))
        if what and what != ".env" or re.search(r"\.kaggle/|\.lightning/|\.modal\.toml", pattern):
            return "deny", READ_REASON.replace("{what}", "listing a provider's key folder")
    return None


# --- interpreter code that reads the environment ------------------------------------------------------------------

# One named variable read, per language: os.environ["X"], os.environ.get("X"), os.getenv("X"), process.env.X,
# process.env["X"], $ENV{X}, ENV["X"], ENV.fetch("X"), ENVIRON["X"], Deno.env.get("X"), getenv("X").
_ONE_VAR = re.compile(
    r"""(?:os\.)?environ\s*(?:\.get\s*\(|\[)\s*['"](\w+)['"]"""
    r"""|(?:os\.)?getenv\s*\(\s*['"](\w+)['"]"""
    r"""|process\.env\s*(?:\.\s*(\w+)|\[\s*['"](\w+)['"]\s*\])"""
    r"""|Deno\.env\.get\s*\(\s*['"](\w+)['"]"""
    r"""|\$ENV\s*\{\s*['"]?(\w+)['"]?\s*\}"""
    r"""|\bENV\s*(?:\[\s*['"](\w+)['"]\s*\]|\.fetch\s*\(\s*['"](\w+)['"])"""
    r"""|ENVIRON\s*\[\s*"(\w+)"\s*\]""")
# What is left after the named reads are taken out: the whole environment (os.environ, environ, getenv,
# process.env, %ENV, $ENV, ENV, ENVIRON, Deno.env, $_ENV, $_SERVER), or a shell-out to env/printenv/set.
_WHOLE_ENV = re.compile(r"\benviron\b|\bgetenv\b|process\.env\b|%ENV\b|\$ENV\b|\bENVIRON\b|Deno\.env\b"
                        r"|\$_ENV\b|\$_SERVER\b")
_RUBY_PERL_ENV = re.compile(r"\bENV\b")
_SHELL_OUT_ENV = re.compile(r"""(?:system|popen|run|call|check_output|getoutput|exec\w*|spawn\w*|qx)\s*[\(\{]\s*\[?\s*"""
                            r"""['"](?:env|printenv|set|export)\b|`\s*(?:env|printenv|set)\s*`|qx\s*[\(\{/]\s*"""
                            r"""(?:env|printenv)\b""")
_OUTPUT = re.compile(r"print|console\.\w+|echo|puts|\bp\b|\bpp\b|\bsay\b|write|stdout|stderr|dump|\bdie\b"
                     r"|\bwarn\b|inspect|\bexit\s*\(|\bsys\.exit\b")


def env_leak(cmd: str, args: list[str]) -> bool:
    """True when interpreter (or awk) code reads the whole environment, or a freelab key, and outputs something:
    `python3 -c 'import os; print(os.environ)'`, `node -e 'console.log(process.env)'`, `perl -e 'print %ENV'`,
    `ruby -e 'p ENV.to_h'`, `awk 'BEGIN{for(k in ENVIRON) print k}'`. One named variable that is not a key
    (`print(os.environ.get("HF_HOME"))`) stays allowed. Script files are not read: only the command line."""
    code = " ".join(args)
    if _SHELL_OUT_ENV.search(code):  # env or printenv run from the code prints by itself
        return True
    outputs = bool(_OUTPUT.search(code)) or (cmd in ("node", "deno", "bun") and
                                             any(a in ("-p", "--print") for a in args))
    if not outputs:
        return False
    names = [n for m in _ONE_VAR.finditer(code) for n in m.groups() if n]
    if any(KEY_WORD.fullmatch(n) for n in names):
        return True
    rest = _ONE_VAR.sub(" ", code)
    if _WHOLE_ENV.search(rest):
        return True
    return cmd in ("ruby", "perl") and bool(_RUBY_PERL_ENV.search(rest))


# --- shell commands -----------------------------------------------------------------------------------------------

_HEREDOC = re.compile(r"""(?<!<)<<(?!<)(-?)\s*(?:'([^'\n]+)'|"([^"\n]+)"|\\?([A-Za-z0-9_.-]+))""")
_FEEDS_INTERPRETER = re.compile(r"(?:^|[\s;&|(/])(python[\d.]*|node|deno|bun|perl|ruby|php)(?=\s|$)")
_FEEDS_SHELL = re.compile(r"(?:^|[\s;&|(/])(?:bash|sh|zsh|dash|ksh)(?=\s|$)")


def split_heredocs(command: str):
    """(the command without its heredoc bodies, [(opener line, body)]). Each body and its closing delimiter line
    are taken out, so the lines of `cat > notes.md <<'EOF' ... EOF` are not read as commands. A heredoc whose
    closing delimiter never comes is left as it is."""
    lines = command.split("\n")
    out, bodies, i = [], [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for m in _HEREDOC.finditer(line):
            delim = m.group(2) or m.group(3) or m.group(4)
            for j in range(i, len(lines)):
                if (lines[j].lstrip("\t") if m.group(1) else lines[j]) == delim:
                    bodies.append((line, "\n".join(lines[i:j])))
                    i = j + 1
                    break
    return "\n".join(out), bodies


def check_heredoc(opener: str, body: str, depth: int):
    """A heredoc fed to an interpreter (`python3 - <<EOF`) is code: deny one that prints the environment or a key
    or reads .env. One fed to a shell (`bash <<EOF`) is checked as commands. Any other (`cat > f <<EOF`, a commit
    message) is text: nothing."""
    m = _FEEDS_INTERPRETER.search(opener)
    if m:
        if KEY_WORD.search(body) and re.search(r"print|console\.log|puts|stdout", body):
            return "deny", DUMP_REASON
        if env_leak("ruby" if m.group(1) in ("ruby", "perl") else "python", [body]):
            return "deny", DUMP_REASON
        if SECRET_IN_CODE.search(body) and re.search(r"open\(|read|load", body):
            return "deny", READ_REASON.replace("{what}", "reading .env or a key file from a script")
    elif _FEEDS_SHELL.search(opener) and depth < 3:
        return check_shell(body, depth + 1)
    return None


def substitutions(word: str) -> list[str]:
    """The commands inside `$(...)` and backticks in one word (`"$(cat .env)"` keeps them inside a token)."""
    out = re.findall(r"`([^`]*)`", word)
    i = word.find("$(")
    while i != -1:
        level, j = 0, i + 1
        while j < len(word):
            level += {"(": 1, ")": -1}.get(word[j], 0)
            if level == 0:
                break
            j += 1
        out.append(word[i + 2:j])
        i = word.find("$(", j)
    return out


def _prepare(command: str) -> str:
    """Unquoted newlines and backticks become `;` (command separators); backslash-newline joins lines."""
    out, quote, i = [], None, 0
    while i < len(command):
        c = command[i]
        if c == "\\" and quote != "'" and i + 1 < len(command):
            if command[i + 1] == "\n":
                out.append(" ")
            else:
                out.append(command[i:i + 2])
            i += 2
            continue
        if quote:
            if c == quote:
                quote = None
            out.append(c)
        elif c in "'\"":
            quote = c
            out.append(c)
        elif c in "\n`":
            out.append(" ; ")
        else:
            out.append(c)
        i += 1
    return "".join(out)


def tokenize(command: str) -> list[str]:
    text = _prepare(split_heredocs(command)[0])
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)
    except ValueError:  # unbalanced quotes: a rough split is enough for a guard
        return re.findall(r"[;&|()<>]+|[^\s;&|()<>]+", text.replace('"', " ").replace("'", " "))


def segments(command: str) -> list[list[str]]:
    segs, cur = [], []
    for tok in tokenize(command):
        if tok in SEPARATORS or (tok and set(tok) <= set("();<>|&") and tok not in REDIRECTS):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        segs.append(cur)
    return segs


def split_redirects(seg: list[str]):
    words, redirs, i = [], [], 0
    while i < len(seg):
        tok = seg[i]
        if tok in REDIRECTS:
            if words and words[-1].isdigit():
                words.pop()  # the fd number of `2>`
            redirs.append((tok, seg[i + 1] if i + 1 < len(seg) else ""))
            i += 2
            continue
        words.append(tok)
        i += 1
    return words, redirs


def base(word: str) -> str:
    return word.rstrip("/").rsplit("/", 1)[-1]


def strip_prefix(words: list[str]) -> list[str]:
    """Drop leading VAR=value assignments and wrappers with their options (sudo -u me, nice -n 5, timeout 5,
    xargs, scripts/withenv, `env -i VAR=1 cmd`)."""
    i = 0
    while i < len(words):
        w = words[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w):
            i += 1
        elif base(w) in WRAPPERS:
            name, i = base(w), i + 1
            while i < len(words) and words[i].startswith("-") and words[i] != "-":
                i += 2 if words[i] in WRAPPERS[name] else 1
            if name == "timeout" and i < len(words):
                i += 1  # the duration
        elif base(w) == "env":
            j = i + 1
            while j < len(words) and (words[j].startswith("-") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[j])):
                j += 2 if words[j] in ("-u", "--unset", "-C", "--chdir", "-S") else 1
            if j >= len(words):
                return words[i:]  # a bare env: the caller sees `env` as the command
            i = j
        else:
            break
    return words[i:]


def is_secret_token(tok: str) -> bool:
    """A word naming .env or a key file, or a shell glob that takes .env (`.*`, `sub/.e*`)."""
    last = base(tok)
    return any(SECRET_TOKEN.search(part) for part in {tok, tok.rsplit("=", 1)[-1]} if part) or (
        last.startswith(".") and bool(re.search(r"[*?\[]", last)) and fnmatch.fnmatch(".env", last))


def _quiet_grep(args: list[str]) -> bool:
    for a in args:
        if a in ("--quiet", "--silent", "--count", "--files-with-matches", "--files-without-match"):
            return True
        if re.match(r"^-[A-Za-z]+$", a) and set(a[1:]) & set("qclL"):
            return True
    return False


def check_segment(words: list[str], redirs, depth: int):
    for op, target in redirs:
        if op in ("<", "<>", "<&") and is_secret_token(target):
            return "deny", READ_REASON.replace("{what}", "feeding .env or a key file into a command")
        if op in (">", ">|", "&>") and base(target) == ".env":
            return "deny", TRUNCATE_REASON
    if depth < 3:
        for w in words + [t for _, t in redirs]:
            for inner in substitutions(w):
                hit = check_shell(inner, depth + 1)
                if hit:
                    return hit
    words = strip_prefix(words)
    if not words:
        return None
    cmd, args = base(words[0]), words[1:]
    secret_args = [a for a in args if is_secret_token(a)]
    if cmd in GREPS and secret_args:  # `--exclude=.env` / `--exclude .env` leaves .env out
        skip = {v for n, v in _grep_parts(cmd, args)[1] if n in ("--exclude", "--ignore")}
        secret_args = [a for a in secret_args if a not in skip and not a.startswith(("--exclude=", "--ignore="))]

    if cmd in SHELLS:  # `bash -c`, `bash -lc`, `sh -ec` ...: the string after the flags is a command
        flag = next((k for k, a in enumerate(args) if re.match(r"^-[A-Za-z]*c[A-Za-z]*$", a)), None)
        if flag is not None and flag + 1 < len(args) and depth < 3:
            return check_shell(args[flag + 1], depth + 1)
    if cmd == "eval" and depth < 3:
        return check_shell(" ".join(args), depth + 1)
    if secret_args:
        if cmd in READERS:
            return "deny", READ_REASON.replace("{what}", f"`{cmd}` on {secret_args[0]}")
        if cmd in COPIERS:
            return "deny", READ_REASON.replace("{what}", f"copying {secret_args[0]} (`{cmd}`)")
        if cmd in GREPS and not _quiet_grep(args):
            return "deny", READ_REASON.replace("{what}", f"`{cmd}` on {secret_args[0]} without -q or -c")
        if cmd in EDITORS:
            return "deny", READ_REASON.replace("{what}", f"`{cmd}` on {secret_args[0]}")
    if cmd in GREPS and not _quiet_grep(args) and grep_leak(cmd, args):
        return "deny", READ_REASON.replace("{what}", f"a recursive `{cmd}` whose pattern matches a key's line in .env "
                                           "(add `--exclude=.env`, or search with -l or -c)")
    if cmd in INTERPRETERS:
        code = " ".join(args)
        if SECRET_IN_CODE.search(code) and not secret_args and re.search(r"\s-[ce]\b|^-[ce]\b", " " + code):
            return "deny", READ_REASON.replace("{what}", f"reading .env or a key file from `{cmd}`")
        if KEY_WORD.search(code) and re.search(r"print|echo|console\.log|puts|write|stdout", code):
            return "deny", DUMP_REASON
    if (cmd in INTERPRETERS or cmd in AWKS) and env_leak(cmd, args):
        return "deny", DUMP_REASON
    if cmd in ("echo", "printf", "print") and any(KEY_REF.search(a) for a in args):
        return "deny", DUMP_REASON
    if cmd == "printenv" and (not args or any(KEY_WORD.fullmatch(a) for a in args)):
        return "deny", DUMP_REASON
    if cmd == "env":  # strip_prefix leaves `env` only when nothing runs after it
        return "deny", DUMP_REASON
    if cmd == "set" and not args:
        return "deny", DUMP_REASON
    if cmd == "export" and (not args or args == ["-p"]):
        return "deny", DUMP_REASON
    if cmd in ("declare", "typeset") and all(a.startswith("-") for a in args):
        return "deny", DUMP_REASON
    if cmd == "modal" and args[:2] in (["token", "info"], ["token", "show"]):
        return "deny", CRED_REASON
    if cmd == "kaggle" and args[:2] == ["config", "view"]:
        return "deny", CRED_REASON
    if any("print-access-token" in w for w in words):
        return "deny", CRED_REASON
    return None


def check_shell(command: str, depth: int = 0):
    command, bodies = split_heredocs(command)
    for opener, body in bodies:
        hit = check_heredoc(opener, body, depth)
        if hit:
            return hit
    for seg in segments(command):
        words, redirs = split_redirects(seg)
        hit = check_segment(words, redirs, depth)
        if hit:
            return hit
    return None


# --- PowerShell -------------------------------------------------------------------------------------------------

_KEYS = "|".join(KEY_NAMES)
_PS_SECRET = r"""(?:^|[\s'"\\/=:,(])(?:\.env(?![\w.-])|\.modal\.toml|\.kaggle[\\/]|\.lightning[\\/])"""
_PS_READ = re.compile(r"(?i)(?:^|[\s;|&({])(?:get-content|gc|type|cat|more|select-string|sls|copy-item|copy|cp|cpi"
                      r"|move-item|move|mv|mi|import-csv|format-hex|fhx|readalltext|readalllines)\b[^|;\n]*?"
                      + _PS_SECRET)
_PS_TRUNCATE = re.compile(r"(?i)(?:\b(?:set-content|sc|out-file)\b[^|;\n]*?|(?<![>\d])>\s*)['\"]?(?:\.[\\/])?"
                          r"\.env(?![\w.-])")
_PS_ENV_DRIVE = re.compile(r"""(?i)(?:^|[\s'"(,])env:[\\/]?(?:\*|(?:%s)\b)?(?=['")\s;|]|$)""" % _KEYS)
_PS_ENV_REF = re.compile(r"(?i)\$\{?env:(?:%s)\b(?!\}?\s*=(?!=))" % _KEYS)
_PS_ENV_API = re.compile(r"""(?i)GetEnvironmentVariables\b|GetEnvironmentVariable\s*\(\s*['"](?:%s)['"]""" % _KEYS)


def check_powershell(command: str):
    """A few cheap PowerShell rules (case-insensitive): reading or copying .env or a key file (`Get-Content .env`,
    `gc`, `type`, `Select-String KAGGLE .env`), overwriting .env, listing the env: drive (`Get-ChildItem env:`) or
    reading a key from it (`$env:KAGGLE_KEY`, `env:KAGGLE_KEY`, [Environment]::GetEnvironmentVariable)."""
    if _PS_READ.search(command):
        return "deny", READ_REASON.replace("{what}", "reading .env or a key file from PowerShell")
    if _PS_TRUNCATE.search(command):
        return "deny", TRUNCATE_REASON
    if _PS_ENV_DRIVE.search(command) or _PS_ENV_REF.search(command) or _PS_ENV_API.search(command):
        return "deny", DUMP_REASON
    return None


# --- cloud deletes and the launch gate ----------------------------------------------------------------------------


FREELAB_VOLUME = "freelab-runs"
FREELAB_STUDIO = "freelab"


def _find(seg: list[str], name: str):
    for i, tok in enumerate(seg):
        if base(tok) == name:
            yield i, seg[i + 1:]


def _names(words: list[str]) -> list[str]:
    """The non-flag words (what a delete names), with `-r`, `-y`, `--teamspace X` style flags left out."""
    out, skip = [], False
    for w in words:
        if skip:
            skip = False
        elif w.startswith("--") and "=" not in w and w not in ("--yes", "--recursive", "--force"):
            skip = True
        elif not w.startswith("-"):
            out.append(w)
    return out


def _flag(words: list[str], *flags: str) -> str | None:
    """The value of `--flag VALUE` or `--flag=VALUE` (the first of `flags` found)."""
    for i, w in enumerate(words):
        for f in flags:
            if w == f and i + 1 < len(words):
                return words[i + 1]
            if w.startswith(f + "="):
                return w[len(f) + 1:]
    return None


def _delete_what(kind: str, names: list[str]) -> str:
    return f"the {kind} `{' '.join(names)}`" if names else f"a {kind}"


def _freelab_slug(name: str) -> bool:
    """A Kaggle kernel or dataset freelab made: OWNER/freelab-... (kaggle.md names every one `freelab-ID` or
    `freelab-EXP`)."""
    return name.rstrip("/").rsplit("/", 1)[-1].startswith("freelab-")


def _run_ids(cwd: str) -> set:
    """freelab's run ids in this project: the folders in lab/runs/ and the runs in lab/status.json."""
    lab = Path(cwd) / "lab"
    ids = set()
    try:
        ids |= {p.name for p in (lab / "runs").iterdir() if p.is_dir()}
    except OSError:
        pass
    try:
        doc = json.loads((lab / "status.json").read_text())
        ids |= {str(r.get("id")) for r in doc.get("runs") or [] if isinstance(r, dict) and r.get("id")}
    except (OSError, ValueError, AttributeError):
        pass
    return ids


def _freelab_job(name: str, cwd: str) -> bool:
    """A Lightning job that is one of freelab's runs: the job name is the run id, a relaunch `ID-r<N>`."""
    if not name:
        return False
    ids = _run_ids(cwd)
    return name in ids or re.sub(r"-r\d+$", "", name) in ids


def _freelab_lightning_path(word: str, cwd: str) -> bool:
    """A Lightning path freelab writes: the `freelab` Studio, `freelab-runs/`, `freelab-init/`, or a job of a
    freelab run (lit://TEAMSPACE/jobs/ID/...)."""
    if re.search(r"(?:^|[/~])freelab-(?:runs|init)(?:/|$)|/studios/freelab(?:/|$)", word):
        return True
    m = re.search(r"lit://[^/]+/[^/]+/jobs/([^/]+)", word) or re.search(r"lit://[^/]+/jobs/([^/]+)", word)
    return bool(m and _freelab_job(m.group(1), cwd))


def freelab_delete(segs, cwd: str):
    """(decision, reason) for a delete of freelab's cloud storage; None for every other command."""
    for seg in segs:
        if any(t in ("--help", "-h") for t in seg):
            continue  # `lightning job delete --help` only prints help
        for _, rest in _find(seg, "modal"):
            if rest[:2] == ["volume", "delete"] and _names(rest[2:])[:1] == [FREELAB_VOLUME]:
                return "deny", VOLUME_DELETE_REASON
            if rest[:2] == ["volume", "rm"]:
                names = _names(rest[2:])
                if names[:1] != [FREELAB_VOLUME]:
                    continue
                what = (f"`{' '.join(names[1:])}` in the Volume `{names[0]}`" if len(names) > 1
                        else f"a folder in the Volume `{names[0]}`") + " on Modal"
                return "ask", ASK_DELETE_REASON.replace("{what}", what)
        for _, rest in _find(seg, "kaggle"):
            if rest[:2] in (["kernels", "delete"], ["datasets", "delete"]):
                names = _names(rest[2:])
                if any(_freelab_slug(n) for n in names):
                    what = _delete_what(rest[0][:-1], names) + " on Kaggle"
                    return "ask", ASK_DELETE_REASON.replace("{what}", what)
        for _, rest in _find(seg, "lightning"):
            if not ("delete" in rest[:2] or rest[:1] == ["rm"]):
                continue
            if rest[:1] == ["rm"]:
                kind, names = "file", _names(rest[1:])
            elif rest[0] == "delete":
                kind, names = "resource", _names(rest[1:])
            else:
                kind, names = rest[0], _names(rest[2:])
            named = names + [v for v in (_flag(rest, "--name"),) if v]
            ours = any(_freelab_lightning_path(n, cwd) for n in named) or \
                (kind == "studio" and FREELAB_STUDIO in named) or \
                (kind == "job" and any(_freelab_job(n, cwd) for n in named))
            if ours:
                return "ask", ASK_DELETE_REASON.replace("{what}", _delete_what(kind, names or named)
                                                        + " on Lightning AI")
    return None


def _path_tail(word: str) -> str:
    return os.path.normpath(word.split("::", 1)[0].replace("\\", "/")).replace("\\", "/")


def _freelab_kernel_dir(rest: list[str], cwd: str) -> bool:
    """`kaggle kernels push -p DIR`: DIR (the current folder without -p) is under lab/backends/, or its
    kernel-metadata.json names a `freelab-` kernel (kaggle.md: lab/backends/kaggle-ID, id OWNER/freelab-ID)."""
    d = _flag(rest, "-p", "--path") or "."
    p = Path(os.path.expanduser(d))
    if not p.is_absolute():
        p = Path(cwd) / p
    p = Path(os.path.normpath(str(p)))
    backends = Path(os.path.normpath(str(Path(cwd) / "lab" / "backends")))
    if backends in p.parents or "/lab/backends/" in "/" + _path_tail(d) + "/":
        return True
    try:
        meta = json.loads((p / "kernel-metadata.json").read_text())
        return _freelab_slug(str(meta.get("id", ""))) or str(meta.get("title", "")).startswith("freelab-")
    except (OSError, ValueError, AttributeError):
        return False


def freelab_launch(seg: list[str], cwd: str) -> str | None:
    """The backend when this command segment is one of freelab's own launches, else None.
    - modal: `modal run` of freelab's app, lab/backends/modal_app.py (modal.md), or with FREELAB_EXP= set;
    - kaggle: `kaggle kernels push` of a kernel folder freelab staged (_freelab_kernel_dir);
    - lightning: `lightning job run` on the `freelab` Studio, or whose command writes to `freelab-runs`;
    - local: the plugin's scripts/backends/local_run.py (not with --dry-run)."""
    for _, rest in _find(seg, "modal"):
        if rest[:1] == ["run"] and (
                any(_path_tail(w).endswith("lab/backends/modal_app.py") for w in rest[1:])
                or any(re.match(r"^FREELAB_(?:EXP|RUNLIB)=", w) for w in seg)):
            return "modal"
    for _, rest in _find(seg, "kaggle"):
        if rest[:2] == ["kernels", "push"] and _freelab_kernel_dir(rest[2:], cwd):
            return "kaggle"
    for _, rest in _find(seg, "lightning"):
        if "run" in rest[:2] and (_flag(rest, "--studio") == FREELAB_STUDIO
                                  or any(re.search(r"(?:^|[/~])freelab-runs(?:/|$)|~/freelab/", w) for w in rest)):
            return "lightning"
    if any(_path_tail(t).endswith("scripts/backends/local_run.py") for t in seg) and "--dry-run" not in seg:
        return "local"
    return None


def _parse_t(s) -> datetime | None:
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        t = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _charter_problems(lab: Path) -> list[str]:
    charter = lab / "charter.md"
    if not charter.is_file():
        return ["no lab/charter.md: run the plan skill"]
    target = budget = False
    label = re.compile(r"^\s*(?:[-*+]|\d+\.)?\s*(?:\*\*|__)?\s*(target|budget)\b[^:\n]*:(.*)$", re.I)
    for line in charter.read_text(errors="replace").splitlines():
        m = label.match(line)
        if not m:
            continue
        if m.group(1).lower() == "target" and re.search(r"\d", m.group(2)):
            target = True
        if m.group(1).lower() == "budget" and m.group(2).strip(" *_"):
            budget = True
    out = []
    if not target:
        out.append("no Target with a number in lab/charter.md: run the plan skill")
    if not budget:
        out.append("no Budget in lab/charter.md: run the plan skill")
    return out


def _last_launch(lab: Path) -> datetime | None:
    p = lab / ".launches"
    if not p.is_file():
        return None
    lines = [l for l in p.read_text(errors="replace").splitlines() if l.strip()]
    return _parse_t(lines[-1].split()[0]) if lines else None


def _has_new_estimate(lab: Path) -> bool:
    p = lab / "ledger.jsonl"
    if not p.is_file():
        return False
    since = _last_launch(lab)
    for line in p.read_text(errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(rec, dict) or rec.get("kind") != "estimate":
            continue
        t = _parse_t(rec.get("t"))
        if t is not None and (since is None or t > since):
            return True
    return False


def gated_launch(segs, cwd: str):
    """(backend, segment text) of the first of freelab's launches the gate covers; None for other commands (the
    user's own launches included). A smoke run (`--smoke`, a `smoke-<backend>` run id) and `--help`/`-h` are exempt,
    each only within the launch's own segment (a `| tee lab/runs/smoke-modal.log` or `&& ls -h` does not count)."""
    for seg in segs:
        backend = freelab_launch(seg, cwd)
        if backend is None:
            continue
        text = " ".join(seg)
        if "--smoke" in text or re.search(r"smoke-(?:modal|kaggle|lightning|local)", text) \
                or any(t in ("--help", "-h") for t in seg):
            continue  # the connection check and help are exempt
        return backend, text
    return None


def check_launch(segs, cwd: str):
    """Deny a gated launch that is not ready. Allowed launches are recorded in lab/.launches by hooks/post.py
    (PostToolUse) once the command succeeded, so a denied, declined or failed launch does not use up its estimate."""
    launch = gated_launch(segs, cwd)
    if launch is None:
        return None
    backend, text = launch
    lab = Path(cwd) / "lab"
    problems = _charter_problems(lab)
    if not _has_new_estimate(lab):
        problems.append("no cost estimate in lab/ledger.jsonl since the last launch: add one with "
                        "`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py add --lab lab --kind estimate --backend "
                        f"{backend} --run ID --usd N --note '...'`")
    # Kaggle is not checked: its cap is `--max-minutes` in ARGS inside the pushed run.py, not in `kernels push`.
    if backend in ("modal", "local", "lightning"):
        capped = re.search(r"--(?:max-)?minutes(?:[\s=]|$)", text) or \
            (backend == "local" and re.search(r"--when[\s=]+night", text))
        if not capped:
            problems.append("no minutes cap: add " + {"modal": "`--minutes N`",
                                                      "local": "`--max-minutes N` after `--`",
                                                      "lightning": "`--max-minutes N` to the job's --command"}[backend])
    if problems:
        return "deny", f"{backend} launch blocked: " + "; ".join(problems) + "."
    return None


def record_launch(lab: Path, backend: str) -> None:
    """Append the launch to lab/.launches: the next gated launch then needs an estimate newer than this one."""
    try:
        lab.mkdir(parents=True, exist_ok=True)
        with (lab / ".launches").open("a") as f:
            f.write(datetime.now(timezone.utc).isoformat(timespec="seconds") + f"\t{backend}\n")
    except OSError:
        pass


# --- main ---------------------------------------------------------------------------------------------------------


def evaluate(data: dict):
    cwd = hook_cwd(data)
    if not uses_freelab(cwd):
        return None
    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    if not isinstance(ti, dict):
        return None
    if tool in ("Bash", "PowerShell"):
        command = ti.get("command")
        if not isinstance(command, str) or not command.strip():
            return None
        hit = (check_powershell(command) if tool == "PowerShell" else None) or check_shell(command)
        if hit:
            return hit
        segs = segments(command)
        return freelab_delete(segs, cwd) or check_launch(segs, cwd)
    return check_file_tool(tool, ti, cwd)


def main() -> int:
    try:
        hit = evaluate(read_input())
        if hit:
            decide(*hit)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
