# Working brief — claude-portable-memory

## What this repo is

A **Claude Code plugin** that relocates Claude Code's auto-memory directory into the
project folder and re-points `autoMemoryDirectory` at it, so memory travels with the repo
across machines. It started life as a private skill at `~/.claude/skills/project-local-auto-memory`
and was copied here to be hardened and published publicly on GitHub.

Goal of the work in this repo: **take the existing skill from "works on my machine" to
"publishable, verified, tested"** — then publish under `phamvietloi/claude-portable-memory`.

## Layout

```
.claude-plugin/marketplace.json          # marketplace manifest (repo root, required location)
plugins/portable-memory/
  .claude-plugin/plugin.json             # plugin manifest
  skills/project-local-auto-memory/
    SKILL.md                             # skill description + instructions
    scripts/setup_project_memory.py      # the actual implementation
tests/                                   # pytest suite (dev-only, not shipped to users)
pyproject.toml
README.md  LICENSE (MIT)  .gitignore
```

## Hard rules

- **Never edit `~/.claude/skills/project-local-auto-memory`.** That is the live installed
  copy on this machine. All changes happen inside this repo. Syncing back is a separate,
  explicit step.
- **Keep the skill directory named `project-local-auto-memory`.** Existing invocations and
  the owner's muscle memory depend on it. The *plugin* is named `portable-memory`; the
  *repo* is `claude-portable-memory`. These three names are deliberate, not an oversight.
- **Keep the Vietnamese trigger phrases** in the SKILL.md `description` ("chuyển auto memory
  về thư mục project", "memory không theo khi đổi máy"). Bilingual triggering is a feature.
- **Do not create or push to a GitHub remote without explicit approval.** The repo is local
  until the owner says go. No `gh repo create`, no `git push`.
- Verify claims against official docs (code.claude.com/docs) rather than memory. This plugin's
  entire value proposition rests on one documented constraint — see backlog item 1.

## Architecture decision (settled 2026-09-18)

**Split by step, not by environment: the AI discovers, the script mutates.**

- **Discovery + judgment → AI.** Where memory currently lives (the running session already
  knows its own auto-memory path — pass it as `--source`; never re-derive what is already in
  context), whether the project sits under `~`, whether to write `settings.json` or
  `settings.local.json`, whether to ask before moving.
- **Mutation → script.** Moving N files with a no-overwrite guarantee, merging one key into a
  settings file that may be hundreds of lines of hooks, detecting Windows junctions, removing
  the emptied source. These need invariants enforced by code, and run-to-run LLM variance is a
  liability here. They are unit-testable; an AI-executed move is not.

**Runtime finding (verified against code.claude.com/docs/en/setup, System requirements):**
Claude Code guarantees **no** runtime. The requirements list OS, RAM, network, shell
(Bash/Zsh/PowerShell/CMD) and ripgrep — no Node, no Python. The npm package only fetches a
native binary and "does not itself invoke Node." On native Windows without Git for Windows
there is no Bash tool at all, only PowerShell.

**Therefore:** keep the Python script as the primary path, and add an **AI-executed fallback**
in SKILL.md gated on "no Python interpreter found". Write the fallback as a strict checklist
that restates the script's invariants, so it stays reviewable:
1. Never overwrite a name that already exists in the target.
2. After writing the settings file, re-read it and confirm the key count is unchanged if
   `autoMemoryDirectory` was already present, otherwise exactly +1. *(Corrected 2026-09-18:
   the original "unchanged +1" only held on a first run — see backlog item 14.)*
3. Never write a relative path into `autoMemoryDirectory`.
4. Skip migration entirely if the source is a symlink/junction.

## Optimization backlog

1. ~~**Re-verify the core constraint.**~~ **DONE 2026-09-18 — CONFIRMED, no change needed.**
   `autoMemoryDirectory` accepts only an absolute or `~/`-prefixed path. Evidence:
   `code.claude.com/docs/en/memory` ("The value must be an absolute path or start with `~/`"),
   `settings-reference.md` ("an absolute or `~/`-prefixed directory path"), and the Claude Code
   2.1.274 bundle's own validator, which rejects non-absolute values. No `${CLAUDE_PROJECT_DIR}`
   expansion exists for this setting — that variable is for hook commands only.
   See `docs/verification-notes.md`.
2. ~~**Default directory name.**~~ **DONE 2026-09-18 — default stays `memory`.**
   Premise was wrong: `--dir-name ".claude/memory"` always worked (verified by a real
   `--dry-run` producing `~/claude-portable-memory/.claude/memory`). Nested names are now
   documented as first-class in SKILL.md ("Choosing `--dir-name`") and README. Both
   side-bugs fixed in the script: the help text now states nested paths work, and the
   "clone to the SAME path" hint prints the project root instead of the memory folder's
   parent.
3. ~~**`slug_for()` is self-described best-effort.**~~ **DONE 2026-09-18 — did both: fixed a
   real bug, then demoted the rest.** The 2.1.274 bundle's derivation is
   `k(e)=e.replace(/[^a-zA-Z0-9]/g,"-")`, wrapped by `JA()` (truncate at `F9=200` + hash) and
   `D_()` (`CLAUDE_CODE_PROJECT_DIR_NAME` override). The old regex only replaced `[:\\/]`, so
   any path with a dot/underscore/space derived a directory Claude Code never created and
   migration silently found nothing — observed live as `tmp.HxtUbsFYfO` vs `tmp-HxtUbsFYfO`.
   `slug_for()` now matches `k()` exactly (13 tests, verified against **2.1.274 on Windows 11**);
   the truncate-hash and env-override branches are deliberately NOT reimplemented — the hash is
   unspecified — but `slug_unreliable_reason()` detects both and the script warns, pointing at
   `--source`. Evidence in `docs/verification-notes.md` §Item 3.
4. ~~**No tests exist.**~~ **DONE 2026-09-18 — 60 tests, `python -m pytest -q` → 60 passed,
   0 skipped** on Windows/Python 3.12.10. Covers `move_contents` (no-overwrite for files AND
   directories, dry-run, idempotency), `to_setting_value` (`~/` vs absolute, Windows drive
   letters, cross-drive fallback), `write_setting` (merge into a hooks-heavy file, malformed
   JSON leaves the file byte-identical), `is_link` (symlink + real junction via `mklink /J`),
   `resolve_target` and `under_claude_rules`. Suite lives in repo-root `tests/`; config in
   `pyproject.toml`.
5. ~~**CI.**~~ **DONE 2026-09-18 — `.github/workflows/ci.yml`, three jobs.** *Manifests:*
   installs Claude Code and runs the official `claude plugin validate . --strict` and
   `… ./plugins/portable-memory --strict` (verified locally to work with a throwaway
   `CLAUDE_CONFIG_DIR` and no login). *Tests:* pytest on ubuntu-latest + windows-latest ×
   Python 3.10/3.11/3.12/3.13 (8 combos), `-ra` so the five Windows-only skips are visible.
   *Lint:* ruff pinned to 0.16.8, plus two repo-specific guards (no test files tracked under
   `plugins/`; the skill script imports stdlib only).
   **Not executed on GitHub Actions** — no remote exists. The YAML parses and both inline
   steps were run locally. First real run is the publish step.
6. ~~**Git-hygiene guidance.**~~ **DONE 2026-09-18.** README "Before you commit memory" now
   gives the pattern and a concrete snippet (`memory/**/*.md` + `!memory/MEMORY.md` — the flat form leaks nested files, verified), plus the
   nested-dir variant. Verified in a scratch repo: `git add -A` stages `MEMORY.md` only, both
   topic files ignored.
7. ~~**Windows verification.**~~ **DONE 2026-09-18 — folklore replaced by a test.**
   `test_to_setting_value_emits_forward_slashes_on_every_platform` asserts the emitted value
   is `~/proj/.claude/memory` with no backslashes; two Windows-only tests pin drive-letter
   handling. Runs green on this machine.
8. **Docs polish for a public audience.** README reworked 2026-09-18 (problem in the first two
   sentences, install above the fold, caveat section). **Remaining:** the short demo recording.
9. ~~**Path-escape guard.**~~ **DONE 2026-09-18.** `resolve_target()` refuses absolute paths,
   drive-qualified names, leading separators, `.`, and `..` escapes; exits 2 with a message
   naming the value. Verified by dry-run (`../outside` and `C:/Windows/Temp/evil` → exit 2)
   and 20 unit tests.
10. ~~**`blockReadsOutsideWorkingDirectories` caveat.**~~ **DONE 2026-09-18 — documented for
    users.** SKILL.md "One caveat worth knowing" quotes the doc sentence and names the silent
    symptom; README has a "Known caveat" section. Judged user-facing because the plugin is
    what triggers it.
11. **Watch the stale schema string.** The shipped settings schema still describes
    `autoMemoryDirectory` as "Ignored if set in projectSettings ... for security", which both the
    docs and the running code contradict (and a live deployment disproves). Re-check on new
    releases — if it ever becomes true, this plugin's default target breaks.
    *(2026-09-18: judged maintainer-only — kept in `docs/verification-notes.md` finding 1.3 and
    here, deliberately NOT in SKILL.md or README. It describes a hypothetical future break, and
    putting it in user docs would undermine the documented behaviour users actually get.)*
12. ~~**Python discovery order.**~~ **DONE 2026-09-18.** SKILL.md "Do this" specifies
    `python3` → `python` → `py`, notes macOS/Linux often lack bare `python`, and names the
    Windows Store-stub failure mode (prints a store prompt, exits non-zero → treat as not
    found). All three failing is the gate for item 14's fallback.
13. ~~**Two install locations.**~~ **DONE 2026-09-18 — better answer found.** SKILL.md "Where
    the script lives" leads with `${CLAUDE_SKILL_DIR}`, which per code.claude.com/docs/en/skills
    is "The directory containing the skill's `SKILL.md` file" and resolves in BOTH layouts, so
    no branching is needed. Both concrete paths are tabled for terminal use;
    `${CLAUDE_PLUGIN_ROOT}` is noted as plugin-only.
14. ~~**AI fallback path.**~~ **DONE 2026-09-18.** SKILL.md "Fallback: no Python on this machine"
    is a 7-step checklist restating the four invariants verbatim plus the containment rule.
    **Correction to the Architecture section above:** invariant 2's "key count is unchanged +1"
    only holds on a first run; on a re-run the key already exists and the count is unchanged.
    The checklist states both cases. Fix the wording above when convenient.
15. ~~**`.claude/rules/` footgun.**~~ **DONE 2026-09-18.** `under_claude_rules()` warns (exit
    stays 0) when the target has adjacent `.claude`/`rules` segments; case-insensitive on
    Windows. 11 tests including a subprocess test proving warn-not-reject.

## Reporting

When finishing a work session, state plainly what was changed, what was verified (with the
source), and what remains. Do not claim something is verified unless a command was run or a
doc was read.
