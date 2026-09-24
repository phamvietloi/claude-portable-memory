"""Tests for scripts/setup_project_memory.py.

The script is stdlib-only and must stay that way; pytest is a dev dependency and
is never needed to run the skill. Import path is configured in pyproject.toml.

Every test here pins a stated invariant of the script rather than its incidental
behaviour: the no-overwrite guarantee when migrating, the "~/ or absolute, never
relative" rule for the settings value, merging into a settings file that may be
hundreds of lines of hooks, and refusing a --dir-name that escapes the project.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
import setup_project_memory as spm

SCRIPT = spm.__file__


def run_script(*args, home=None, env_extra=None):
    """Run the script in a subprocess with a fully controlled environment.

    Every subprocess test must pin HOME, because several of the script's
    warnings depend on whether the project sits under the home directory. Left
    to the ambient environment that is an accident of the platform: pytest's
    tmp_path is under %TEMP% (inside the user profile) on Windows but under
    /tmp (outside $HOME) on Linux, so the same assertion meant different things
    on each OS. Setting both HOME and USERPROFILE covers os.path.expanduser on
    POSIX and Windows respectively.

    CLAUDE_CODE_PROJECT_DIR_NAME is scrubbed unless a test asks for it, so a
    developer who happens to have it set doesn't see spurious failures.
    """
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_PROJECT_DIR_NAME", None)
    if home is not None:
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True, text=True, env=env, check=False,
    )


def warning_lines(stderr):
    """The WARNING lines only, so a test can assert on the set it expects."""
    return [ln for ln in stderr.splitlines() if ln.startswith("WARNING")]


# --------------------------------------------------------------------------
# resolve_target — the path-escape guard
# --------------------------------------------------------------------------

ACCEPTED = [
    ("memory", ["memory"]),
    (".claude/memory", [".claude", "memory"]),
    ("a/b/c", ["a", "b", "c"]),
    ("memory/", ["memory"]),                 # trailing separator absorbed
    ("  memory  ", ["memory"]),              # surrounding whitespace stripped
    ("./memory", ["memory"]),                # explicit "here" prefix
    ("sub/../memory", ["memory"]),           # climbs back in, never escapes
]


@pytest.mark.parametrize("dir_name,parts", ACCEPTED)
def test_resolve_target_accepts_plain_and_nested_names(tmp_path, dir_name, parts):
    """A single folder and a nested relative path are both supported.

    '.claude/memory' matters specifically: a real deployment uses it, and an
    earlier reading of the code wrongly assumed --dir-name could not express it.
    """
    root = str(tmp_path)
    assert spm.resolve_target(root, dir_name) == os.path.join(root, *parts)


def test_resolve_target_accepts_windows_separator_on_windows(tmp_path):
    if os.name != "nt":
        pytest.skip("backslash is a legal filename character on POSIX")
    root = str(tmp_path)
    assert spm.resolve_target(root, ".claude\\memory") == os.path.join(
        root, ".claude", "memory"
    )


def test_resolve_target_returns_normalised_absolute_path(tmp_path):
    """The return value is abspath'd, so mixed separators never reach the caller."""
    target = spm.resolve_target(str(tmp_path), ".claude/memory")
    assert os.path.isabs(target)
    assert target == os.path.normpath(target)


REJECTED = [
    "",                       # empty
    "   ",                    # whitespace only
    "..",                     # the parent itself
    "../outside",             # classic escape
    "a/../../outside",        # escape via a detour
    ".",                      # resolves to the project root itself
    "C:/Windows/Temp/evil",   # absolute, drive-qualified
    "C:\\Windows\\Temp\\evil",
    "D:foo",                  # drive-relative: ntpath.join sends this to D:'s cwd
    "/tmp/x",                 # POSIX-absolute; on Windows joins to C:/tmp/x
    "\\\\server\\share",      # UNC
]


@pytest.mark.parametrize("dir_name", REJECTED)
def test_resolve_target_rejects_escaping_values(tmp_path, dir_name):
    """Memory outside the project stops travelling with the repo, so this is an
    error, not a warning. Previously these silently 'succeeded'."""
    with pytest.raises(ValueError):
        spm.resolve_target(str(tmp_path), dir_name)


def test_resolve_target_error_names_the_offending_value(tmp_path):
    with pytest.raises(ValueError) as excinfo:
        spm.resolve_target(str(tmp_path), "../outside")
    message = str(excinfo.value)
    assert "'../outside'" in message
    assert "--dir-name" in message


def test_resolve_target_rejects_absolute_even_when_inside_the_project(tmp_path):
    """An absolute value is refused outright, including one that happens to point
    inside the project: --project-root is the supported way to retarget."""
    inside = str(tmp_path / "memory")
    with pytest.raises(ValueError) as excinfo:
        spm.resolve_target(str(tmp_path), inside)
    assert "--project-root" in str(excinfo.value)


def test_resolve_target_does_not_touch_the_filesystem(tmp_path):
    """Pure validation: it resolves a path, it does not create one."""
    target = spm.resolve_target(str(tmp_path), ".claude/memory")
    assert not os.path.exists(target)


# --------------------------------------------------------------------------
# slug_for / slug_unreliable_reason
#
# Pinned against Claude Code 2.1.274, whose derivation is quoted verbatim in the
# script. These tests assert what the script produces; they cannot assert that a
# future Claude Code still agrees, which is exactly why --source is preferred.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    # The slug this machine's Claude Code actually used for this repo.
    (r"C:\Users\alice\claude-portable-memory", "C--Users-alice-claude-portable-memory"),
    # A dot is replaced too. The old regex left it, producing a slug that
    # matched no real directory — observed live as 'tmp.HxtUbsFYfO'.
    (r"C:\Users\alice\AppData\Local\Temp\tmp.HxtUbsFYfO",
     "C--Users-alice-AppData-Local-Temp-tmp-HxtUbsFYfO"),
    (r"C:\work\my_project", "C--work-my-project"),           # underscore
    (r"C:\work\my project", "C--work-my-project"),           # space
    ("C:\\work\\caf\u00e9", "C--work-caf-"),                 # non-ASCII (café)
    ("/home/u/proj.v2", "-home-u-proj-v2"),                  # POSIX
    ("/home/u/proj", "-home-u-proj"),
])
def test_slug_for_replaces_every_non_alphanumeric(path, expected):
    assert spm.slug_for(path) == expected


def test_slug_for_matches_claude_codes_character_class():
    """k(e) in the 2.1.274 bundle is /[^a-zA-Z0-9]/g — nothing narrower."""
    sample = "aZ09" + "".join(chr(c) for c in range(33, 48))
    assert spm.slug_for(sample) == "aZ09" + "-" * 15


def test_slug_unreliable_reason_is_none_for_an_ordinary_path(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_PROJECT_DIR_NAME", raising=False)
    assert spm.slug_unreliable_reason(r"C:\Users\alice\proj") is None


def test_slug_unreliable_reason_flags_the_env_override(monkeypatch):
    """D_ = o6r() ?? JA(e): the env var replaces the derivation entirely."""
    monkeypatch.setenv("CLAUDE_CODE_PROJECT_DIR_NAME", "work")
    reason = spm.slug_unreliable_reason(r"C:\Users\alice\proj")
    assert reason is not None
    assert "CLAUDE_CODE_PROJECT_DIR_NAME" in reason


def test_slug_unreliable_reason_flags_the_truncation_branch(monkeypatch):
    """Over F9=200 chars Claude Code appends a hash we cannot reproduce."""
    monkeypatch.delenv("CLAUDE_CODE_PROJECT_DIR_NAME", raising=False)
    long_path = "/home/u/" + "x" * 250
    assert len(spm.slug_for(long_path)) > spm.SLUG_MAX_LEN
    reason = spm.slug_unreliable_reason(long_path)
    assert reason is not None
    assert "200" in reason


def test_slug_boundary_at_exactly_the_limit(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_PROJECT_DIR_NAME", raising=False)
    at_limit = "x" * spm.SLUG_MAX_LEN
    assert spm.slug_unreliable_reason(at_limit) is None
    assert spm.slug_unreliable_reason(at_limit + "x") is not None


def test_unreliable_slug_warns_at_the_command_line(tmp_path):
    """Warn, don't fail: the run still completes, it just can't migrate."""
    project = tmp_path / "proj"
    project.mkdir()
    result = run_script("--dry-run", "--project-root", str(project),
                        home=tmp_path,
                        env_extra={"CLAUDE_CODE_PROJECT_DIR_NAME": "work"})
    assert result.returncode == 0, result.stderr
    assert len(warning_lines(result.stderr)) == 1, result.stderr
    assert "CLAUDE_CODE_PROJECT_DIR_NAME" in result.stderr
    assert "--source" in result.stderr


def test_no_slug_warning_when_source_is_given(tmp_path):
    """--source makes the derivation irrelevant, so there is nothing to warn about."""
    project = tmp_path / "proj"
    project.mkdir()
    result = run_script("--dry-run", "--project-root", str(project),
                        "--source", str(tmp_path / "somewhere"),
                        home=tmp_path,
                        env_extra={"CLAUDE_CODE_PROJECT_DIR_NAME": "work"})
    assert result.returncode == 0, result.stderr
    assert warning_lines(result.stderr) == []


# --------------------------------------------------------------------------
# under_claude_rules — warn, but do not reject
# --------------------------------------------------------------------------

@pytest.mark.parametrize("dir_name", [
    ".claude/rules",              # the rules directory itself
    ".claude/rules/memory",
    ".claude/rules/deep/nested",
    "sub/.claude/rules/memory",   # nested .claude/rules dirs load too
])
def test_under_claude_rules_detects_rule_directories(tmp_path, dir_name):
    target = spm.resolve_target(str(tmp_path), dir_name)
    assert spm.under_claude_rules(str(tmp_path), target) is True


@pytest.mark.parametrize("dir_name", [
    "memory",
    ".claude/memory",
    "rules/memory",          # 'rules' without the '.claude' parent is unrelated
    ".claude/rulesets/x",    # exact segment match, not a prefix match
    ".claude/memory/rules",  # 'rules' not directly under '.claude'
])
def test_under_claude_rules_ignores_everything_else(tmp_path, dir_name):
    target = spm.resolve_target(str(tmp_path), dir_name)
    assert spm.under_claude_rules(str(tmp_path), target) is False


def test_under_claude_rules_is_case_insensitive_on_windows(tmp_path):
    if os.name != "nt":
        pytest.skip("POSIX paths are case-sensitive, so .claude/RULES is a different dir")
    target = spm.resolve_target(str(tmp_path), ".claude/RULES/memory")
    assert spm.under_claude_rules(str(tmp_path), target) is True


def test_claude_rules_warns_but_does_not_reject(tmp_path):
    """The requirement is warn, not reject: the run must still succeed. A unit
    test on the predicate alone would not prove that wiring."""
    project = tmp_path / "proj"
    project.mkdir()
    result = run_script("--dry-run", "--project-root", str(project),
                        "--dir-name", ".claude/rules/memory", home=tmp_path)
    assert result.returncode == 0, result.stderr
    assert len(warning_lines(result.stderr)) == 1, result.stderr
    assert ".claude/rules/" in result.stderr
    assert "Memory target" in result.stdout


def test_no_warning_for_the_recommended_nested_name(tmp_path):
    """The happy path is silent — and with HOME pinned, that is true on every OS.

    The project sits under HOME here, so the '~/' branch is the one exercised;
    an unpinned HOME made this assertion accidental (see run_script).
    """
    project = tmp_path / "proj"
    project.mkdir()
    result = run_script("--dry-run", "--project-root", str(project),
                        "--dir-name", ".claude/memory", home=tmp_path)
    assert result.returncode == 0, result.stderr
    assert warning_lines(result.stderr) == []
    assert "'~/proj/.claude/memory'" in result.stdout, result.stdout


def test_project_outside_home_warns_and_writes_an_absolute_value(tmp_path):
    """The branch Linux CI stumbled into, now covered deliberately on every OS.

    With HOME pinned beside the project rather than above it, a portable '~/'
    value is impossible, so the script must say so and fall back to absolute.
    """
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "elsewhere"
    project.mkdir()
    result = run_script("--dry-run", "--project-root", str(project),
                        "--dir-name", "memory", home=home)
    assert result.returncode == 0, result.stderr
    warnings = warning_lines(result.stderr)
    assert len(warnings) == 1, result.stderr
    assert "NOT under your home directory" in warnings[0]
    # Absolute, forward-slashed, and emphatically not a '~/' value.
    expected = str(project / "memory").replace(os.sep, "/")
    assert f"'{expected}'" in result.stdout, result.stdout
    assert "'~/" not in result.stdout


# --------------------------------------------------------------------------
# to_setting_value — "~/ or absolute, never relative"
# --------------------------------------------------------------------------

def test_to_setting_value_uses_tilde_form_under_home(tmp_path):
    home = tmp_path / "home"
    target = home / "proj" / "memory"
    value, is_tilde = spm.to_setting_value(str(target), str(home))
    assert (value, is_tilde) == ("~/proj/memory", True)


def test_to_setting_value_emits_forward_slashes_on_every_platform(tmp_path):
    """Pins the Windows behaviour the skill relies on: the value written to
    settings.json uses '/' separators even though the local paths use '\\'."""
    home = tmp_path / "home"
    target = home / "proj" / ".claude" / "memory"
    value, is_tilde = spm.to_setting_value(str(target), str(home))
    assert value == "~/proj/.claude/memory"
    assert is_tilde is True
    assert "\\" not in value


def test_to_setting_value_falls_back_to_absolute_outside_home(tmp_path):
    home = tmp_path / "home"
    target = tmp_path / "elsewhere" / "memory"
    value, is_tilde = spm.to_setting_value(str(target), str(home))
    assert is_tilde is False
    assert "\\" not in value
    assert value == str(target).replace(os.sep, "/")
    # Still a valid setting value: Claude Code requires absolute or "~/".
    assert os.path.isabs(value.replace("/", os.sep))


def test_to_setting_value_never_emits_the_rejected_tilde_dot_form(tmp_path):
    """Degenerate but reachable: a project root that is an ancestor of home.

    Claude Code normalizes the part after "~/" and refuses a bare "." — the
    setting would be silently ignored and memory would go to the default
    directory. The absolute form is emitted instead.
    """
    home = tmp_path / "home"
    value, is_tilde = spm.to_setting_value(str(home), str(home))
    assert value != "~/."
    assert is_tilde is False
    assert value == str(home).replace(os.sep, "/")


@pytest.mark.skipif(os.name != "nt", reason="drive letters are Windows-only")
def test_to_setting_value_across_windows_drives_is_absolute():
    """commonpath() raises ValueError across drives; the function must fall back
    to the absolute form rather than propagating that. Pure path math — the
    drives need not exist."""
    value, is_tilde = spm.to_setting_value("D:\\data\\memory", "C:\\Users\\someone")
    assert (value, is_tilde) == ("D:/data/memory", False)


@pytest.mark.skipif(os.name != "nt", reason="drive letters are Windows-only")
def test_to_setting_value_keeps_drive_letter_in_absolute_form():
    value, is_tilde = spm.to_setting_value("C:\\work\\proj\\memory", "D:\\home")
    assert (value, is_tilde) == ("C:/work/proj/memory", False)


# --------------------------------------------------------------------------
# move_contents — the no-overwrite guarantee
# --------------------------------------------------------------------------

def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_move_contents_never_overwrites_an_existing_name(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _write(src / "new.md", "from source")
    _write(src / "clash.md", "SOURCE VERSION")
    _write(dst / "clash.md", "DESTINATION VERSION")

    moved, skipped = spm.move_contents(str(src), str(dst), dry=False)

    assert moved == ["new.md"]
    assert skipped == ["clash.md"]
    # The destination's copy wins and is left byte-identical.
    assert (dst / "clash.md").read_text(encoding="utf-8") == "DESTINATION VERSION"
    # The source's copy is left in place rather than deleted, so nothing is lost.
    assert (src / "clash.md").read_text(encoding="utf-8") == "SOURCE VERSION"
    assert (dst / "new.md").read_text(encoding="utf-8") == "from source"
    assert not (src / "new.md").exists()


def test_move_contents_moves_a_subdirectory_intact(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _write(src / "topics" / "deep" / "note.md", "nested content")

    moved, skipped = spm.move_contents(str(src), str(dst), dry=False)

    assert moved == ["topics"]
    assert skipped == []
    assert (dst / "topics" / "deep" / "note.md").read_text(encoding="utf-8") == "nested content"
    assert not (src / "topics").exists()


def test_move_contents_skips_an_existing_directory_name(tmp_path):
    """The no-overwrite rule applies to directories too, not just files."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    _write(src / "topics" / "from_src.md", "src")
    _write(dst / "topics" / "from_dst.md", "dst")

    moved, skipped = spm.move_contents(str(src), str(dst), dry=False)

    assert moved == []
    assert skipped == ["topics"]
    assert not (dst / "topics" / "from_src.md").exists()
    assert (dst / "topics" / "from_dst.md").exists()
    assert (src / "topics" / "from_src.md").exists()


def test_move_contents_creates_a_missing_destination(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _write(src / "MEMORY.md", "index")

    moved, _ = spm.move_contents(str(src), str(dst), dry=False)

    assert moved == ["MEMORY.md"]
    assert (dst / "MEMORY.md").exists()


def test_move_contents_dry_run_changes_nothing(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _write(src / "a.md", "a")
    _write(src / "b.md", "b")

    moved, skipped = spm.move_contents(str(src), str(dst), dry=True)

    assert moved == ["a.md", "b.md"]
    assert skipped == []
    assert not dst.exists()
    assert (src / "a.md").exists() and (src / "b.md").exists()


def test_move_contents_is_idempotent_on_a_second_run(tmp_path):
    """Re-running is safe: everything is already at the destination, so the
    second pass moves nothing and overwrites nothing."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    _write(src / "a.md", "a")
    spm.move_contents(str(src), str(dst), dry=False)
    _write(src / "a.md", "a different a")

    moved, skipped = spm.move_contents(str(src), str(dst), dry=False)

    assert (moved, skipped) == ([], ["a.md"])
    assert (dst / "a.md").read_text(encoding="utf-8") == "a"


# --------------------------------------------------------------------------
# write_setting — merge without clobbering, fail loudly on bad JSON
# --------------------------------------------------------------------------

EXISTING_SETTINGS = {
    "permissions": {"deny": ["Bash(rm -rf /)", "Bash(format:*)"], "defaultMode": "auto"},
    "hooks": {
        "PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "lint.sh"}]}
        ]
    },
    "env": {"FOO": "bar"},
}


def test_write_setting_merges_without_clobbering_other_keys(tmp_path):
    """The real settings.json may be hundreds of lines of hooks; adding one key
    must leave every other key byte-for-byte equivalent."""
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps(EXISTING_SETTINGS, indent=2), encoding="utf-8")

    change = spm.write_setting(str(settings), "~/proj/memory", dry=False)

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["autoMemoryDirectory"] == "~/proj/memory"
    for key, value in EXISTING_SETTINGS.items():
        assert data[key] == value
    assert len(data) == len(EXISTING_SETTINGS) + 1
    assert change == {"old": None, "new": "~/proj/memory"}


def test_write_setting_reports_the_previous_value(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"autoMemoryDirectory": "~/old/memory"}), encoding="utf-8")

    change = spm.write_setting(str(settings), "~/new/memory", dry=False)

    assert change == {"old": "~/old/memory", "new": "~/new/memory"}
    assert json.loads(settings.read_text(encoding="utf-8"))["autoMemoryDirectory"] == "~/new/memory"


def test_write_setting_is_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(EXISTING_SETTINGS, indent=2), encoding="utf-8")

    spm.write_setting(str(settings), "~/proj/memory", dry=False)
    first = settings.read_bytes()
    change = spm.write_setting(str(settings), "~/proj/memory", dry=False)

    assert settings.read_bytes() == first
    assert change["old"] == change["new"] == "~/proj/memory"


def test_write_setting_creates_the_file_and_its_parent(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"

    spm.write_setting(str(settings), "~/proj/memory", dry=False)

    assert json.loads(settings.read_text(encoding="utf-8")) == {
        "autoMemoryDirectory": "~/proj/memory"
    }


def test_write_setting_treats_an_empty_file_as_empty_settings(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("   \n", encoding="utf-8")

    spm.write_setting(str(settings), "~/proj/memory", dry=False)

    assert json.loads(settings.read_text(encoding="utf-8")) == {
        "autoMemoryDirectory": "~/proj/memory"
    }


def test_write_setting_errors_clearly_on_malformed_json_and_writes_nothing(tmp_path):
    """Contract is "fix or remove it before re-running" — which means the broken
    file must be left exactly as found, not partially rewritten."""
    settings = tmp_path / "settings.json"
    broken = '{"permissions": {"deny": [  <-- not json\n'
    settings.write_text(broken, encoding="utf-8")
    before = settings.read_bytes()

    with pytest.raises(SystemExit) as excinfo:
        spm.write_setting(str(settings), "~/proj/memory", dry=False)

    assert "not valid JSON" in str(excinfo.value)
    assert str(settings) in str(excinfo.value)
    assert settings.read_bytes() == before


def test_write_setting_dry_run_creates_nothing(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"

    change = spm.write_setting(str(settings), "~/proj/memory", dry=True)

    assert change == {"old": None, "new": "~/proj/memory"}
    assert not settings.exists()
    assert not settings.parent.exists()


def test_write_setting_dry_run_leaves_an_existing_file_untouched(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(EXISTING_SETTINGS, indent=2), encoding="utf-8")
    before = settings.read_bytes()

    spm.write_setting(str(settings), "~/proj/memory", dry=True)

    assert settings.read_bytes() == before


# --------------------------------------------------------------------------
# is_link — POSIX symlinks and Windows junctions
# --------------------------------------------------------------------------

def test_is_link_false_for_a_real_directory(tmp_path):
    real = tmp_path / "memory"
    real.mkdir()
    assert spm.is_link(str(real)) is False


def test_is_link_false_for_a_regular_file(tmp_path):
    f = tmp_path / "MEMORY.md"
    f.write_text("index", encoding="utf-8")
    assert spm.is_link(str(f)) is False


def test_is_link_false_for_a_missing_path(tmp_path):
    assert spm.is_link(str(tmp_path / "nope")) is False


def test_is_link_true_for_a_symlink(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
    except OSError as e:  # Windows without Developer Mode: WinError 1314
        pytest.skip(f"cannot create symlinks here: {e}")
    assert spm.is_link(str(link)) is True


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
def test_is_link_true_for_a_windows_junction(tmp_path):
    """This is the reason is_link() exists: os.path.islink() does not report a
    junction, so the reparse-point attribute has to be checked directly."""
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"mklink /J failed: {result.stdout.strip()} {result.stderr.strip()}")

    assert os.path.islink(str(link)) is False, "precondition: islink misses junctions"
    assert spm.is_link(str(link)) is True
