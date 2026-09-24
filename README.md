# Portable Memory — a Claude Code plugin

**Claude Code's auto memory is per-machine.** Clone your repo somewhere else and
everything Claude learned about the project stays behind, stranded under
`~/.claude/projects/<slug>/memory/` on the old machine.

This plugin moves those memory files **into the project** and re-points
`autoMemoryDirectory` at them, so memory becomes part of the repo — portable,
reviewable in diffs, and git-trackable.

## Install

```
/plugin marketplace add phamvietloi/claude-portable-memory
/plugin install portable-memory@claude-portable-memory
```

Prefer no plugin manager? Copy `plugins/portable-memory/skills/project-local-auto-memory`
into `~/.claude/skills/` and restart Claude Code.

## Use

Ask Claude in the target project:

> make auto-memory live in this project so it follows the repo

or run the script directly — the path below is the manual-install location; for a
plugin install, substitute the plugin's `skills/project-local-auto-memory` directory:

```bash
python3 ~/.claude/skills/project-local-auto-memory/scripts/setup_project_memory.py \
  --source "<current auto-memory dir>"
```

Inside a Claude session the skill refers to that directory as `${CLAUDE_SKILL_DIR}`,
which resolves in both layouts. If `python3` isn't found, try `python`, then `py` — and
if none of the three exist, the skill has a no-Python fallback that Claude executes
step by step.

Useful flags: `--dry-run`, `--project-root <path>`, `--dir-name <path>`,
`--settings-file settings.local.json`.

## How it works

1. Resolve the project root (git toplevel, else CWD).
2. Move existing memory files into `<project>/memory` — never overwriting what is
   already there.
3. Write `autoMemoryDirectory` into `<project>/.claude/settings.json`, merging with
   existing keys.

`autoMemoryDirectory` accepts only an absolute path or a `~/`-prefixed one. An
invalid value isn't an error — Claude Code silently uses the default directory
instead — so portability is a convention, not a literal relative path:

- **Project under `$HOME`** → a `~/`-relative value is written and committed; it resolves
  on any machine that clones to the same `~`-relative path.
- **Cloned elsewhere** → re-run the skill on that machine (it detects the existing
  `memory/` folder, migrates nothing, rewrites only the pointer). Use
  `--settings-file settings.local.json` so machine-specific paths stay out of git.

### Where the memory folder goes

`<project>/memory` by default. A nested path is fully supported and a good choice
if you'd rather keep the project root clean:

```bash
python3 ~/.claude/skills/project-local-auto-memory/scripts/setup_project_memory.py \
  --dir-name ".claude/memory"
```

The path must stay inside the project — absolute values and `../` escapes are
refused, since memory outside the project would stop travelling with the repo.
Avoid `.claude/rules/…`: every `.md` there loads as a project rule, so your memory
files would be injected into context as instructions. The script warns if you try.

## Before you commit memory

Auto memory records whatever Claude learned about the project, which can include
operational detail you would not publish. The recommended pattern is to **commit
the `MEMORY.md` index and gitignore the per-topic files** it points at:

```gitignore
memory/**/*.md
!memory/MEMORY.md
```

Use `**/`, not `memory/*.md` — Claude files detailed notes into subdirectories, and a
single-level glob would leave `memory/topics/*.md` committed.

Using `--dir-name ".claude/memory"`? Adjust both lines to match
(`.claude/memory/**/*.md` and `!.claude/memory/MEMORY.md`).

That keeps the shape of the memory reviewable in the repo while the detailed notes
stay local. If you do want the topic files committed, skim them first — tokens and
internal hostnames end up there.

## Known caveat

If `permissions.blockReadsOutsideWorkingDirectories` is set to `true` in any
settings scope, Claude Code loads no auto memory from a directory chosen by a
repository-supplied settings file — *even one inside the project*. The key is unset
by default. The symptom is silent: memory simply stops loading and saving.

## License

MIT — see [LICENSE](LICENSE).
