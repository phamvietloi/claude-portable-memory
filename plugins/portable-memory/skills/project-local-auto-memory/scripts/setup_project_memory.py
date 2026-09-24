#!/usr/bin/env python3
"""Relocate Claude Code auto-memory INTO the project directory so it travels
with the repo (git/copy) instead of living under ~/.claude/projects/<slug>/.

Why: by default auto-memory is stored per-machine under the user's home, keyed
by a sanitized absolute project path. That directory does not move when you
clone/copy the project to another machine, so the accumulated memory is lost.
Putting the memory files inside <project>/memory and pointing
`autoMemoryDirectory` at them makes the content version-controllable and
portable.

What this does (idempotent — safe to re-run):
  1. Figure out the project root (git toplevel if in a repo, else CWD).
  2. Ensure <project>/<dir-name> exists (default dir-name: "memory"; a nested
     relative path such as ".claude/memory" works too, but it must stay inside
     the project — an absolute or ".."-escaping value is refused).
  3. If an existing auto-memory dir is found at the default user location
     (or one passed via --source), MOVE its contents into the project dir
     without overwriting anything already there.
  4. Write `autoMemoryDirectory` into <project>/.claude/<settings-file>,
     merging with any existing keys. The value uses the "~/..." form when the
     project lives under your home directory (so a clone to the same
     ~-relative path on another machine just works); otherwise it falls back
     to an absolute path and warns.

The value MUST be an absolute path or start with "~/": Claude Code does not
accept relative paths like "./memory" for this setting, because auto-memory is
resolved at session startup independent of the working subdirectory.
"""
from __future__ import annotations

import argparse
import json
import ntpath
import os
import re
import shutil
import subprocess
import sys


def eprint(*a):
    print(*a, file=sys.stderr)


def git_toplevel(start: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        return None
    if out.returncode != 0:
        return None
    top = out.stdout.strip()
    return os.path.abspath(top) if top else None


# Claude Code's own derivation, read verbatim out of the 2.1.274 bundle:
#
#     var F9 = 200;
#     function k(e){ return e.replace(/[^a-zA-Z0-9]/g, "-") }
#     function Le(e){ return Math.abs(K9(e)).toString(36) }
#     function JA(e){ let n = k(e); if (n.length <= F9) return n;
#                     return `${n.slice(0, F9)}-${Le(e)}` }
#     function D_(e){ return o6r() ?? JA(e) }
#
# slug_for() reimplements k() only. It deliberately does not attempt JA()'s
# truncate-and-hash branch (Le() wraps an unspecified hash) or D_()'s env
# override — see slug_unreliable_reason(), which detects both and tells the
# caller to pass --source instead.
SLUG_MAX_LEN = 200  # F9


def slug_for(abspath: str) -> str:
    """Best-effort reimplementation of Claude Code's project-slug derivation:
    every character outside [a-zA-Z0-9] becomes '-'.

    Verified against Claude Code 2.1.274 on Windows 11 (see the quoted source
    above and docs/verification-notes.md). Note this is wider than path
    separators alone — dots, underscores, spaces and non-ASCII are replaced
    too, so 'C:\\Temp\\tmp.AbC' becomes 'C--Temp-tmp-AbC', not 'C--Temp-tmp.AbC'.

    This remains a fallback. The authoritative value is the auto-memory path the
    running session already knows — pass it via --source for certainty.
    """
    return re.sub(r"[^a-zA-Z0-9]", "-", abspath)


def slug_unreliable_reason(abspath: str) -> str | None:
    """Return why a derived slug provably cannot match Claude Code's, or None.

    These are the two branches slug_for() does not reimplement. Both are
    detectable even though neither is reproducible.
    """
    if os.environ.get("CLAUDE_CODE_PROJECT_DIR_NAME"):
        return ("CLAUDE_CODE_PROJECT_DIR_NAME is set, which replaces the derived "
                "project directory name entirely")
    if len(slug_for(abspath)) > SLUG_MAX_LEN:
        return (f"the derived slug exceeds {SLUG_MAX_LEN} characters, so Claude Code "
                "truncates it and appends a hash this script cannot reproduce")
    return None


def default_memory_dir(project_root: str) -> str:
    return os.path.join(
        os.path.expanduser("~"), ".claude", "projects",
        slug_for(project_root), "memory",
    )


def resolve_target(project_root: str, dir_name: str) -> str:
    """Join dir_name onto project_root and return the absolute target, refusing
    any value that would put the memory outside the project.

    A nested relative path is fine and supported: "memory", ".claude/memory"
    and (on Windows) ".claude\\memory" all work. What is refused:

      - absolute paths, and paths starting with a separator — on Windows
        os.path.join("C:\\proj", "/tmp/x") is "C:/tmp/x", outside the project;
      - drive-qualified names — os.path.join("C:\\proj", "D:foo") is "D:foo",
        i.e. a different drive's current directory (checked on CPython 3.12);
      - anything that climbs out with "..", and "." itself.

    Memory placed outside the project silently stops travelling with the repo,
    which is the one thing this skill exists to do, so this is an error rather
    than a warning.
    """
    name = dir_name.strip()
    if not name:
        raise ValueError("--dir-name must not be empty.")
    # ntpath is consulted on every platform, not just Windows: a drive-qualified
    # name is refused identically everywhere so the rule (and its tests) don't
    # change meaning depending on where the script runs.
    if (os.path.isabs(name) or ntpath.isabs(name)
            or os.path.splitdrive(name)[0] or ntpath.splitdrive(name)[0]
            or name.startswith(("/", "\\"))):
        raise ValueError(
            f"--dir-name must be a path relative to the project root, got {name!r}. "
            "Memory stored outside the project would not travel with the repo. "
            "To set up a different project, use --project-root instead."
        )

    root = os.path.abspath(project_root)
    target = os.path.abspath(os.path.join(root, name))
    try:
        contained = target != root and os.path.commonpath([root, target]) == root
    except ValueError:  # different drives, or a mix of abs/relative
        contained = False
    if not contained:
        raise ValueError(
            f"--dir-name must stay inside the project root, got {name!r} "
            f"(resolves to {target}, project root is {root})."
        )
    return target


def under_claude_rules(project_root: str, target: str) -> bool:
    """True when target sits inside a `.claude/rules/` directory.

    Claude Code loads every .md under `.claude/rules/` recursively as a project
    rule, so memory files put there would be injected into context as
    instructions on every session. Containment-wise it is a legal choice, so
    this only drives a warning — see main().
    """
    rel = os.path.relpath(os.path.abspath(target), os.path.abspath(project_root))
    if os.name == "nt":
        rel = os.path.normcase(rel)
    parts = rel.replace("\\", "/").split("/")
    return any(a == ".claude" and b == "rules"
               for a, b in zip(parts, parts[1:], strict=False))


def to_setting_value(target: str, home: str) -> tuple[str, bool]:
    """Return (value, is_tilde). Use ~/ form if target is under home."""
    target = os.path.abspath(target)
    home = os.path.abspath(home)
    try:
        common = os.path.commonpath([target, home])
    except ValueError:
        common = None
    if common == home:
        rel = os.path.relpath(target, home).replace(os.sep, "/")
        if rel == ".":
            # target IS the home directory. Claude Code's validator normalizes the
            # part after "~/" and rejects a bare "." — the setting would then be
            # silently ignored — so emit the absolute form, which it accepts.
            return home.replace(os.sep, "/"), False
        return "~/" + rel, True
    return target.replace(os.sep, "/"), False


def is_link(path: str) -> bool:
    # Catches POSIX symlinks and Windows junctions/symlinks.
    if os.path.islink(path):
        return True
    if os.name == "nt":
        try:
            attrs = os.stat(path, follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
            return bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
        except (OSError, AttributeError):
            return False
    return False


def move_contents(src: str, dst: str, dry: bool) -> tuple[list[str], list[str]]:
    """Move every entry from src into dst, skipping (not overwriting) names
    that already exist in dst. Returns (moved, skipped)."""
    moved, skipped = [], []
    os.makedirs(dst, exist_ok=True) if not dry else None
    for name in sorted(os.listdir(src)):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.exists(d):
            skipped.append(name)
            continue
        moved.append(name)
        if not dry:
            shutil.move(s, d)
    return moved, skipped


def write_setting(settings_path: str, value: str, dry: bool) -> dict:
    data: dict = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, encoding="utf-8") as f:
                txt = f.read().strip()
                data = json.loads(txt) if txt else {}
        except json.JSONDecodeError as e:
            raise SystemExit(
                f"ERROR: {settings_path} is not valid JSON ({e}); "
                "fix or remove it before re-running."
            ) from e
    old = data.get("autoMemoryDirectory")
    data["autoMemoryDirectory"] = value
    if not dry:
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
    return {"old": old, "new": value}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-root", help="Project root (default: git toplevel or CWD)")
    ap.add_argument("--source", help="Existing auto-memory dir to migrate FROM. "
                    "Pass the auto-memory path your current Claude session reports "
                    "for certainty; otherwise it's auto-derived.")
    ap.add_argument("--dir-name", default="memory",
                    help="Where inside the project to keep the memory files. A nested "
                         "relative path works too, e.g. '.claude/memory'. Must stay "
                         "inside the project root (default: memory)")
    ap.add_argument("--settings-file", default="settings.json",
                    choices=["settings.json", "settings.local.json"],
                    help="Which .claude settings file to write (default: settings.json)")
    ap.add_argument("--dry-run", action="store_true", help="Show actions without making changes")
    args = ap.parse_args()

    home = os.path.expanduser("~")
    cwd = os.getcwd()
    project_root = os.path.abspath(args.project_root) if args.project_root \
        else (git_toplevel(cwd) or cwd)

    if not os.path.isdir(project_root):
        eprint(f"ERROR: project root does not exist: {project_root}")
        return 2

    try:
        target = resolve_target(project_root, args.dir_name)
    except ValueError as e:
        eprint(f"ERROR: {e}")
        return 2
    if under_claude_rules(project_root, target):
        eprint("WARNING: that path is inside '.claude/rules/', where Claude Code loads "
               "every .md file recursively as a project rule — each memory file would be "
               "injected into every session as an instruction. Prefer '.claude/memory'. "
               "Continuing, since the path is otherwise valid.")
    settings_path = os.path.join(project_root, ".claude", args.settings_file)

    src = os.path.abspath(args.source) if args.source else default_memory_dir(project_root)
    if not args.source:
        reason = slug_unreliable_reason(project_root)
        if reason:
            eprint(f"WARNING: cannot derive the existing auto-memory location here — {reason}. "
                   "Pass --source with the auto-memory path your Claude session reports, "
                   "or nothing will be migrated.")
    src_is_target = os.path.abspath(src) == os.path.abspath(target)

    tag = "[dry-run] " if args.dry_run else ""
    print(f"{tag}Project root : {project_root}")
    print(f"{tag}Memory target: {target}")
    print(f"{tag}Settings file: {settings_path}")
    print(f"{tag}Migrate from : {src}"
          + ("  (derived)" if not args.source else "")
          + ("  [same as target — nothing to migrate]" if src_is_target else ""))

    # --- migrate ---
    if not src_is_target and os.path.isdir(src) and not is_link(src) and os.listdir(src):
        moved, skipped = move_contents(src, target, args.dry_run)
        print(f"{tag}Moved {len(moved)} item(s): {', '.join(moved) or '-'}")
        if skipped:
            print(f"{tag}Skipped (already present, NOT overwritten): {', '.join(skipped)}")
        # tidy up empty source so Claude Code doesn't keep an orphan dir
        if not args.dry_run and os.path.isdir(src) and not os.listdir(src):
            try:
                os.rmdir(src)
                print(f"Removed now-empty source dir: {src}")
            except OSError:
                pass
    elif is_link(src):
        print(f"{tag}Source is a symlink/junction — skipping migration "
              f"(resolve it manually if needed).")
    else:
        if not args.dry_run:
            os.makedirs(target, exist_ok=True)
        print(f"{tag}No external memory to migrate; ensured target exists.")

    # --- config ---
    value, is_tilde = to_setting_value(target, home)
    if not is_tilde:
        eprint("WARNING: project is NOT under your home directory, so a portable "
               "'~/' value isn't possible. Writing an absolute path instead — it "
               "will only be correct on THIS machine; re-run on each machine.")
    change = write_setting(settings_path, value, args.dry_run)
    if change["old"] == value:
        print(f"{tag}autoMemoryDirectory already set to: {value}")
    else:
        print(f"{tag}autoMemoryDirectory: {change['old']!r} -> {value!r}")

    print()
    print("Next steps:")
    print("  1. Restart Claude Code (new session) for the setting to take effect.")
    print("  2. If prompted, ACCEPT the workspace-trust dialog — project/local")
    print("     settings are only honored after trust is granted.")
    print("  3. Verify with /memory (open the auto-memory folder).")
    if is_tilde and args.settings_file == "settings.json":
        rel = os.path.relpath(target, project_root).replace(os.sep, "/")
        # The clone path is the PROJECT ROOT, not the memory folder's parent —
        # those differ for any nested --dir-name such as '.claude/memory'.
        root_value, _ = to_setting_value(project_root, home)
        print(f"  4. Commit '{rel}/' and '.claude/{args.settings_file}' so memory")
        print("     travels with the repo. On another machine, clone to the SAME")
        print(f"     ~-relative path ({root_value}) and it works automatically;")
        print("     if you clone elsewhere, just re-run this skill there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
