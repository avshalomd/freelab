"""Checks on the text of the skills (skills/*/SKILL.md and their references/):

- amounts are not written as "$N" (Claude Code substitutes $0, $1 ... and $ARGUMENTS in SKILL.md);
- every file named as ${CLAUDE_PLUGIN_ROOT}/... exists;
- each description fits the 1024-character limit and all of them together stay inside a budget (they are all
  in the agent's context from the start of a session);
- every --flag quoted next to resources.py, ledger.py, local_run.py, poll.py, stats.py, cleanup.py or env.sh is a
  real option of that script (read from its --help);
- every "`skill` §N" and "`skill` step N" resolves to a numbered heading (or sub-item) in that skill;
- status.json fields are changed with `status_page.py set` (a key it accepts), not by hand.

Not checked, because the prose is too loose to parse reliably: a bare "§N" in a references/ file, a bare
"step N", "section N" and "its §3, step 4" (which skill is meant is clear to a reader, not to a regex)."""
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
SKILL_FILES = sorted(SKILLS.glob("*/SKILL.md"))
MD_FILES = sorted(SKILLS.glob("**/*.md"))
BACKENDS = ("modal", "kaggle", "lightning", "local")


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def test_no_argument_placeholders_in_skill_files():
    bad = []
    for p in SKILL_FILES:
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if re.search(r"\$\d|\$ARGUMENTS", line):
                bad.append(f"{p.relative_to(SKILLS)}:{n}: {line.strip()}")
    assert not bad, "write amounts as 'USD N', not '$N':\n" + "\n".join(bad)


# --- (a) referenced files exist ---------------------------------------------------------------------------

PLUGIN_PATH = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}((?:/[\w.<>|*-]+)+)")


def expand(path: str) -> list[str]:
    """Expand <backend> over the four backends and <a|b|c> over its alternatives; [] when a placeholder or a glob
    (<other>, *, ID, NNN) remains, so that path is not checked."""
    paths = [path]
    while True:
        m = re.search(r"<([\w|]+)>", paths[0])
        if not m:
            break
        names = BACKENDS if m.group(1) == "backend" else m.group(1).split("|")
        if m.group(1) != "backend" and not all(n in BACKENDS for n in names):
            return []
        paths = [p.replace(m.group(0), n, 1) for p in paths for n in names]
    return [] if any(c in p for p in paths for c in "<>*|") else paths


def test_every_referenced_plugin_file_exists():
    missing, checked = [], 0
    for md in MD_FILES:
        text = md.read_text()
        for m in PLUGIN_PATH.finditer(text):
            raw = m.group(1).rstrip(".,;:")
            for p in expand(raw):
                checked += 1
                if not (ROOT / p.lstrip("/")).exists():
                    missing.append(f"{rel(md)}:{line_of(text, m.start())}: ${{CLAUDE_PLUGIN_ROOT}}{p}")
    assert checked > 20, "the check found almost no paths: has the reference form changed?"
    assert not missing, "referenced files that do not exist:\n" + "\n".join(missing)


def test_every_skill_relative_reference_file_exists():
    """`references/NAME.md` named inside a skill is a file in that skill's own references/ folder."""
    missing = []
    for md in MD_FILES:
        skill_dir = SKILLS / md.relative_to(SKILLS).parts[0]
        text = md.read_text()
        for m in re.finditer(r"(?<![\w/}.])references/([\w-]+\.md)", text):
            if not (skill_dir / "references" / m.group(1)).exists():
                missing.append(f"{rel(md)}:{line_of(text, m.start())}: references/{m.group(1)}")
    assert not missing, "referenced files that do not exist:\n" + "\n".join(missing)


# --- (b) descriptions ---------------------------------------------------------------------------------------

DESCRIPTION_LIMIT = 1024
DESCRIPTION_TOTAL = 2600


def descriptions() -> dict[str, str]:
    out = {}
    for p in SKILL_FILES:
        front = p.read_text().split("---")[1]
        m = re.search(r"^description:[ \t]*(.+)$", front, re.M)
        assert m, f"{rel(p)}: no one-line description in the front matter"
        out[p.parent.name] = m.group(1).strip()
    return out


def test_each_description_fits_the_limit():
    too_long = {k: len(v) for k, v in descriptions().items() if len(v) > DESCRIPTION_LIMIT}
    assert not too_long, f"descriptions over {DESCRIPTION_LIMIT} characters: {too_long}"


def test_descriptions_stay_inside_the_total_budget():
    lengths = {k: len(v) for k, v in descriptions().items()}
    assert sum(lengths.values()) <= DESCRIPTION_TOTAL, (
        f"all descriptions together are {sum(lengths.values())} characters (budget {DESCRIPTION_TOTAL}): {lengths}")


# --- (c) quoted --flags are real options --------------------------------------------------------------------

SCRIPTS = {
    "resources.py": ROOT / "scripts" / "resources.py",
    "ledger.py": ROOT / "scripts" / "ledger.py",
    "local_run.py": ROOT / "scripts" / "backends" / "local_run.py",
    "poll.py": ROOT / "scripts" / "poll.py",
    "stats.py": ROOT / "scripts" / "stats.py",
    "cleanup.py": ROOT / "scripts" / "cleanup.py",
    "env.sh": ROOT / "scripts" / "env.sh",
}
MENTION = re.compile(r"(?<![\w.])(" + "|".join(re.escape(s) for s in SCRIPTS) + r")(?![\w])")
FLAG = re.compile(r"(?<![\w-])(--[a-z][\w-]*)")


def run_help(*cmd: str) -> str:
    r = subprocess.run([sys.executable, *cmd, "--help"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"{' '.join(cmd)} --help failed: {r.stderr}"
    return r.stdout


@lru_cache(maxsize=None)
def script_options(name: str) -> tuple[frozenset, dict]:
    """(flags of the top-level parser, {subcommand: flags}) for a script, from its --help output.
    env.sh is not argparse: its flags are the ones its own text mentions (none)."""
    path = SCRIPTS[name]
    if name == "env.sh":
        return frozenset(FLAG.findall(path.read_text())) | {"--help"}, {}
    top = run_help(str(path))
    flags = frozenset(FLAG.findall(top)) | {"--help"}
    subs = {}
    m = re.search(r"\{([\w,-]+)\}", top)
    for sub in (m.group(1).split(",") if m else []):
        subs[sub] = frozenset(FLAG.findall(run_help(str(path), sub))) | {"--help"}
    return flags, subs


def command_segments(text: str):
    """Yield (script, offset, segment) for each mention of a script: the text from the mention to the closing
    backtick (inline code), the end of the command line (a fenced block, honouring a trailing backslash), a blank
    line or an '&&', and before the next script mentioned or a bare '--' (the experiment's own flags)."""
    body_start = text.find("\n---", 3) + 4 if text.startswith("---") else 0  # skip the front matter
    for m in MENTION.finditer(text, body_start):
        fenced = text.count("```", 0, m.start()) % 2 == 1
        i, end = m.end(), len(text)
        while i < end:
            c = text[i]
            if c == "`":
                end = i
            elif c == "\n" and (text[i - 1] != "\\" if fenced else text[i + 1:i + 2] == "\n"):
                end = i
            elif text.startswith("&&", i):
                end = i
            else:
                i += 1
                continue
        seg = text[m.end():end]
        nxt = MENTION.search(seg)
        seg = seg[:nxt.start()] if nxt else seg
        yield m.group(1), m.start(), re.split(r"(?<!\S)--(?!\S)", seg)[0]  # after a bare "--" come the experiment's own flags


def test_quoted_flags_are_real_options():
    bad, seen = [], 0
    for md in MD_FILES:
        text = md.read_text()
        for script, pos, seg in command_segments(text):
            flags = FLAG.findall(seg)
            if not flags:
                continue
            top, subs = script_options(script)
            first = next((t for t in seg.split() if not t.startswith("-")), "")
            allowed = top | subs[first] if first in subs else top.union(*subs.values())
            for f in flags:
                seen += 1
                if f not in allowed:
                    bad.append(f"{rel(md)}:{line_of(text, pos)}: {script} {first} {f}: not an option")
    assert seen > 20, "the check found almost no flags: has the command style changed?"
    assert not bad, "quoted flags that the script does not have:\n" + "\n".join(bad)


# --- (d) cross-references: "`skill` §N" and "`skill` step N" -----------------------------------------------

SKILL_NAMES = {p.parent.name for p in SKILL_FILES}
REF = re.compile(r"`(\w+)`(?: skill)?,?\s+(§(\d+)(?:(?:,| or| and)\s+§(\d+))*|step\s+(\d+)([a-z])?)")


@lru_cache(maxsize=None)
def headings(skill: str) -> dict[int, str]:
    """{N: the text of section N} for the '## N. Title' headings of a skill."""
    text = (SKILLS / skill / "SKILL.md").read_text()
    parts = re.split(r"^## (\d+)\. .*$", text, flags=re.M)  # [before, "1", body1, "2", body2, ...]
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def test_skill_cross_references_resolve():
    bad, seen = [], 0
    for md in MD_FILES:
        text = md.read_text()
        for m in REF.finditer(text):
            skill = m.group(1)
            if skill not in SKILL_NAMES:
                continue
            where = f"{rel(md)}:{line_of(text, m.start())}: `{skill}` {m.group(2).replace(chr(10), ' ')}"
            sections = headings(skill)
            if m.group(5):  # step N[letter]
                seen += 1
                n = int(m.group(5))
                body = sections.get(n)
                if body is None:
                    bad.append(f"{where}: {skill} has no section {n}")
                elif m.group(6) and not re.search(rf"^\s*{m.group(6)}\. ", body, re.M):
                    bad.append(f"{where}: section {n} of {skill} has no item {m.group(6)}.")
            else:
                for n in map(int, re.findall(r"§(\d+)", m.group(2))):
                    seen += 1
                    if n not in sections:
                        bad.append(f"{where}: {skill} has no section {n}")
    assert seen > 20, "the check found almost no references: has the reference style changed?"
    assert not bad, "references that do not resolve:\n" + "\n".join(bad)


def own_skill_refs():
    """Bare '§N' in a SKILL.md means that skill's own section N."""
    for p in SKILL_FILES:
        text = p.read_text()
        for m in re.finditer(r"(?<![`\w] )(?<!`\s)(?<!`)§(\d+)", text):
            before = text[max(0, m.start() - 40):m.start()]
            if re.search(r"`\w+`(?: skill)?,?\s*$", before) or re.search(r"§\d+(?:,| or| and)\s*$", before):
                continue  # qualified (or chained to a qualified reference): the test above covers it
            yield p, m


def test_bare_section_references_resolve_in_their_own_skill():
    bad = []
    for p, m in own_skill_refs():
        n = int(m.group(1))
        if n not in headings(p.parent.name):
            bad.append(f"{rel(p)}:{line_of(p.read_text(), m.start())}: §{n}: {p.parent.name} has no section {n}")
    assert not bad, "bare § references that do not resolve:\n" + "\n".join(bad)


# --- (e) status.json fields change through status_page.py, never by hand ----------------------------------------

SET_USE = re.compile(r"status_page\.py set --lab lab ([\w.|]+)")


def test_status_json_fields_are_set_with_the_command():
    """The poll rewrites status.json on every check, so the skills change its fields with `status_page.py set`
    (and events with `status_page.py event`), never with a hand edit; each key they set is one `set` accepts."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import status_page
    status = (SKILLS / "status" / "SKILL.md").read_text()
    assert "status_page.py set --lab lab" in status and "status_page.py event --lab lab" in status
    assert "have no command" not in status and "right before you edit it" not in status
    used = set()
    for f in SKILL_FILES:
        for m in SET_USE.finditer(f.read_text()):
            used.update(m.group(1).split("|"))
    assert used, "no skill uses status_page.py set"
    for key in used:
        assert key.split(".")[0] in status_page.SET_KEYS, f"`status_page.py set` has no key {key!r}"
