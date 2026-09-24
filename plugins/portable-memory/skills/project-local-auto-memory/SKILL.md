---
name: project-local-auto-memory
description: >-
  Relocate Claude Code's auto-memory directory INTO the current project folder
  (as <project>/memory) and point `autoMemoryDirectory` at it, so the
  accumulated memory travels with the repo across machines instead of being
  stranded under ~/.claude/projects/<slug>/. Use this whenever the user wants
  project memory to be portable, version-controlled, committed to git, or
  shared with teammates — e.g. "make auto-memory live in the project", "move
  memory into the repo so it follows to another machine", "set up
  project-local / portable memory", "my memory doesn't follow when I clone the
  project", "chuyển auto memory về thư mục project", "memory không theo khi
  đổi máy". Also use to re-establish the pointer on a NEW machine after cloning
  a project that already carries a memory/ folder.
---

# Project-local auto-memory

## Why this exists

By default Claude Code stores auto-memory at `~/.claude/projects/<slug>/memory/`,
where `<slug>` is a sanitized absolute path to the project. That location is
**per-machine and outside the project**, so when you copy or clone the project
to another machine the memory does not come with it — you start from an empty
memory. Moving the memory files inside the project and re-pointing
`autoMemoryDirectory` makes them part of the repo: portable, reviewable, and
git-trackable.

## The one constraint that shapes everything

`autoMemoryDirectory` only accepts **an absolute path or a path starting with
`~/`** — never a relative `./memory`. This is documented: "The value must be an
absolute path or start with `~/`" (code.claude.com/docs/en/memory), and the
settings reference gives the type as "an absolute or `~/`-prefixed directory
path". An invalid value is **not** an error — Claude Code silently falls back to
the default directory, so a typo looks like success. This is why portability
needs a small convention rather than a literal relative path (see "How
portability works" below).

## Where the script lives

Use `${CLAUDE_SKILL_DIR}` — it expands to the directory holding this SKILL.md in
both install layouts, so you never have to guess which one you are in:

```
${CLAUDE_SKILL_DIR}/scripts/setup_project_memory.py
```

The two concrete locations, for when you are typing a path by hand in a terminal:

| Installed as | Path |
| --- | --- |
| Plugin (`/plugin install portable-memory@…`) | `${CLAUDE_PLUGIN_ROOT}/skills/project-local-auto-memory/scripts/` |
| Copied manually | `~/.claude/skills/project-local-auto-memory/scripts/` |

`${CLAUDE_PLUGIN_ROOT}` is substituted only in plugin skills; `${CLAUDE_SKILL_DIR}`
works in both, so prefer it.

## Do this

Run the bundled script from (or pointed at) the project root. It is idempotent —
safe to re-run any time.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/setup_project_memory.py [--source "<current-memory-dir>"]
```

**Interpreter probe order: `python3` → `python` → `py`.** Use the first that
prints a version. Do not assume bare `python` exists — macOS and most Linux
distributions ship only `python3`. On Windows the reverse trap applies: `python3`
is often the Microsoft Store stub, which prints a store prompt and exits
non-zero; treat that as "not found" and fall through to `python`, then to the
`py` launcher. If **all three** fail, there is no Python on this machine — use
the manual fallback at the bottom of this file.

**Pass `--source` with the auto-memory directory your current session reports.**
A running Claude session already knows its auto-memory path (it appears in your
context, typically `~/.claude/projects/<slug>/memory`). Passing it as `--source`
is more reliable than letting the script re-derive the slug, which is a
best-effort fallback and can differ across Claude Code versions/OSes. If you
genuinely don't know it, omit `--source` and the script derives a candidate.

The script will:
1. Resolve the project root (git toplevel if in a repo, else CWD).
2. Move any existing memory files from `--source` into `<project>/memory`,
   **without overwriting** anything already there.
3. Write `autoMemoryDirectory` into `<project>/.claude/settings.json`, merging
   with existing keys. It uses the `~/...` form when the project is under your
   home directory, else an absolute path (with a warning).

Then tell the user the next steps the script prints: **restart Claude Code**,
**accept the workspace-trust dialog** if prompted (project/local settings are
only honored after trust), and verify with `/memory`.

### Useful flags
- `--dry-run` — preview every action without changing anything. Good to show
  the user first if they're cautious.
- `--project-root <path>` — target a project other than the current directory.
- `--settings-file settings.local.json` — write the pointer to the machine-local
  (gitignored) settings file instead of the committed `settings.json`. Use this
  when the path can't be portable (see below) so a machine-specific absolute
  path never gets committed.
- `--dir-name <path>` — where inside the project the memory lives.

### Choosing `--dir-name`

The default is `memory`, i.e. `<project>/memory`. **A nested relative path is a
first-class option, not a workaround:** `--dir-name ".claude/memory"` works and
is a good choice when you'd rather not add a folder to the project root.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/setup_project_memory.py --dir-name ".claude/memory"
```

The value must stay **inside** the project: an absolute path, or one that climbs
out with `..`, is refused outright, because memory stored outside the project
would silently stop travelling with the repo — the one thing this skill exists
to prevent. To set up a different project, use `--project-root`.

One nested path to avoid: anything under **`.claude/rules/`**. Claude Code loads
every `.md` there recursively as a project rule, so each memory file would be
injected into every session as an instruction. The script warns if you point it
there and continues; pick `.claude/memory` instead.

## How portability works (explain this to the user)

The memory **files** live in `<project>/memory` and travel with the repo via
git or copy. The **pointer** (`autoMemoryDirectory`) is the only thing that's
location-sensitive. Two strategies:

- **`~/`-relative, committed (default).** If the project always lives at the
  same path relative to home on every machine (e.g. you always clone to
  `~/work/<name>`), the committed value `~/work/<name>/memory` resolves
  correctly everywhere with zero extra steps. The script picks this
  automatically whenever the project is under `~`.
- **Re-run per machine.** If you clone to different locations on different
  machines, the committed `~/` value won't match. Just **re-run this skill** on
  the new machine — it detects the already-present `memory/` folder (nothing to
  migrate) and rewrites the pointer to the correct local path. Prefer
  `--settings-file settings.local.json` here so each machine keeps its own path
  and you don't commit a machine-specific absolute path.

If the project is **not** under your home directory at all, a `~/` value is
impossible; the script falls back to an absolute path and warns. In that case
recommend `--settings-file settings.local.json` and the per-machine re-run.

## One caveat worth knowing

If `permissions.blockReadsOutsideWorkingDirectories` is turned on, this setup
stops working — silently. The docs are explicit: "While
`permissions.blockReadsOutsideWorkingDirectories` is on, Claude Code loads no
auto memory from a directory that a repository-supplied settings file chooses
and saves none to it, **wherever that directory sits**"
(code.claude.com/docs/en/memory). Because this skill's whole mechanism is a
repository-supplied settings file, that applies even though the memory
directory is inside the project.

The key defaults to unset, so most setups are unaffected. **Symptom:** memory
stops loading and saving with no error. If a user reports that, check for this
key in every settings scope — any one file setting it to `true` is enough.

## Git hygiene

Commit `.claude/settings.json` (the pointer) so it travels with the repo. For
the memory files themselves, the safer default is to **commit only the
`MEMORY.md` index and gitignore the per-topic files**, which is where sensitive
operational detail accumulates:

```gitignore
memory/**/*.md
!memory/MEMORY.md
```

Use `**/` rather than `memory/*.md`: Claude files detailed notes into
subdirectories, and a single-level glob would leave `memory/topics/*.md`
committed. Adjust both lines if you used a different `--dir-name`.

Auto-memory records whatever Claude learned about the project — sometimes
tokens, internal hostnames, or customer detail. Before committing to a shared or
public repo, skim `memory/*.md`. If in doubt, keep the repo private or move the
sensitive notes out.

## Verifying it worked

There is no need to trust blindly — confirm:
- `cat <project>/.claude/settings.json` shows the expected `autoMemoryDirectory`.
- `<project>/memory/MEMORY.md` exists and the old `~/.claude/projects/<slug>/memory`
  is gone (or empty).
- After restarting, `/memory` → "open auto memory folder" points into the project.

## Fallback: no Python on this machine

Claude Code guarantees no language runtime — its system requirements list a
shell and ripgrep, not Python. If the probe order above (`python3` → `python` →
`py`) turns up **nothing**, do the work yourself with file and shell tools.

Do not improvise. The script exists because these steps have invariants that are
easy to get wrong by hand, and you are replacing tested code with judgement.
Follow this checklist in order and verify each step before moving on.

**Step 1 — gather.** Project root (git toplevel, else CWD); the current
auto-memory directory (it is already in your context — do not re-derive it); the
home directory; the chosen `--dir-name` (default `memory`).

**Step 2 — check the target directory choice.**

> **Never write a relative path into `autoMemoryDirectory`.**

The value must be absolute or start with `~/`. Additionally:
- Use the `~/` form **only** if the project root is under the home directory.
  Compute it as `~/` + the project's path relative to home + `/` + the dir-name,
  with forward slashes, even on Windows.
- Otherwise write the **absolute** path, and write it to
  `.claude/settings.local.json` rather than `settings.json`, so a
  machine-specific path is not committed.
- Never emit `~/.` — Claude Code normalizes the part after `~/` and rejects a
  bare `.`, and the setting is then silently ignored.

**Step 3 — check containment.**

> The memory directory must stay inside the project root.

Reject an absolute `--dir-name`, and reject anything that resolves outside the
project (a leading `..`, a drive letter). Warn, but continue, if the path lands
under `.claude/rules/` — every `.md` there loads as a project rule.

**Step 4 — decide whether to migrate.**

> **Skip migration entirely if the source is a symlink/junction.**

If the current auto-memory directory is a symlink (POSIX) or a junction
(Windows), do not move anything. Say so and let the user resolve it by hand.

**Step 5 — move the files.**

> **Never overwrite a name that already exists in the target.**

Create the target directory. For each entry in the source, if a file or folder
with that name already exists in the target, **skip it and leave the source copy
in place** — do not overwrite, do not merge, do not delete. Report which names
were moved and which were skipped. Remove the source directory afterwards only
if it is now empty.

**Step 6 — write the setting.**

> **After writing the settings file, re-read it and confirm the key count is
> unchanged +1.**

Read `<project>/.claude/<settings-file>`. If it exists but is not valid JSON,
**stop** and tell the user to fix or remove it — do not overwrite it. Otherwise
set the single key `autoMemoryDirectory` and write the file back, preserving
every other key exactly (it may hold hundreds of lines of hooks and
permissions). Then re-read and count: the key count must be **exactly +1 if
`autoMemoryDirectory` was absent, and unchanged if it was already present** (the
re-run case). Any other outcome means you clobbered something — restore and stop.

**Step 7 — report.** Tell the user what moved, what was skipped, the old and new
setting value, and the same next steps the script prints: restart Claude Code,
accept the workspace-trust dialog, verify with `/memory`.
