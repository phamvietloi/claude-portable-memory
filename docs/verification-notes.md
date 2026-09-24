# Verification notes

Working notes for the `claude-portable-memory` optimization backlog. Each entry records the
claim, what was actually checked, verbatim evidence, and a verdict.

Quoted command output is verbatim except that the author's Windows username was
replaced with `alice` throughout, including inside derived slugs.

**Session date:** 2026-09-18
**Claude Code version used as the reference implementation:** `2.1.274` (`claude --version` →
`2.1.274 (Claude Code)`), bundle at `C:\Users\alice\.local\bin\claude`
**Docs fetched:** 2026-09-18 from `code.claude.com/docs` (`/en/memory`, `/en/settings-reference.md`,
`/en/env-vars.md`)
**Platform:** Windows 11 Pro 26200, Python 3.12, PowerShell/Git-Bash

Covered in the first session: backlog items **1** and **2**. Item **3** was added later, below.

> **Status note (2026-09-18).** This file is a record of what was *verified*, written at the
> time. Several "Recommended changes (not applied)" listed under item 2 have since been
> applied, and the script has changed. For the current state of the work, read the
> optimization backlog in `CLAUDE.md`; treat this file as evidence, not as a to-do list.

---

## Item 1 — Re-verify the core constraint on `autoMemoryDirectory`

### The claim

`SKILL.md` ("The one constraint that shapes everything") and the module docstring of
`scripts/setup_project_memory.py` both assert:

> `autoMemoryDirectory` only accepts **an absolute path or a path starting with `~/`** — never a
> relative `./memory`.

Backlog item 1 asks whether a project-relative form or a `${CLAUDE_PROJECT_DIR}`-style expansion is
supported today.

### What was checked

1. `https://code.claude.com/docs/en/memory` (fetched 2026-09-18) — "Auto memory → Storage location".
2. `https://code.claude.com/docs/en/settings-reference.md` (raw markdown, fetched 2026-09-18) —
   the `### autoMemoryDirectory` section at line 2664, plus a full-page search for
   `CLAUDE_PROJECT_DIR` / "variable expansion" / "expand".
3. `https://code.claude.com/docs/en/env-vars.md` — searched for every memory-related variable.
4. The shipped Claude Code 2.1.274 bundle: extracted the settings-schema description, the
   settings-scope resolver, and the path validator/expander.

### Evidence

**(a) Docs — `/en/memory`, "Storage location" (verbatim):**

> To store auto memory in a different location, set `autoMemoryDirectory` in your `settings.json`.
> It is read from any [settings scope](/docs/en/settings#settings-precedence): user, project, local,
> policy, or `--settings`.
>
> ```json
> {
>   "autoMemoryDirectory": "~/my-custom-memory-dir"
> }
> ```
>
> **The value must be an absolute path or start with `~/`.**

(emphasis added; the sentence is unemphasised in the original)

**(b) Docs — `/en/settings-reference.md`, lines 2664–2678 (verbatim):**

~~~~
### `autoMemoryDirectory`

Store [auto memory](/docs/en/memory#storage-location) in a directory of your choice instead of the per-project default.

* **Scope**: [`Any file`](#scopes)
* **Type**: string, an absolute or `~/`-prefixed directory path
* **Default**: unset, so Claude Code uses `~/.claude/projects/<project>/memory/`

```json settings.json
{
  "autoMemoryDirectory": "~/my-memory-dir"
}
```

From project or local settings, Claude Code honors this key under the same [workspace trust rule as hooks](/docs/en/permissions#what-runs-before-you-trust-a-folder), since a cloned repository can supply those files.
~~~~

**(c) Implementation — the validator, from the 2.1.274 bundle (verbatim, minified):**

```js
function Lm(e,n){
  if(!e)return;
  let r=e;
  if(n&&(r.startsWith("~/")||r.startsWith("~\\"))){
    let m=r.slice(2),h=lc(m||".");
    if(h==="."||h===".."||h.startsWith(`..${ti}`)||h.startsWith("../")||h.startsWith("..\\"))return;
    r=ei(Dpe(),m)
  }
  let s=lc(r).replace(/[/\\]+$/,"");
  if(MB(s))return;
  return(s+ti).normalize("NFC")
}
function MB(e){return!Npe(e)||e.length<3||/^[A-Za-z]:$/.test(e)||Vp(e)||e.includes("\x00")}
```

The minified identifiers are resolved by the module's own import line, found verbatim in the same
bundle — this is not inference:

```js
import{homedir as Dpe}from"os";
import{isAbsolute as Npe,join as ei,normalize as lc,sep as ti}from"path";
```

So `MB` (the reject predicate) reads: **reject if `!path.isAbsolute(value)`**, or length < 3, or the
value is a bare drive letter (`C:`), or `Vp(value)` (predicate not resolved — name collides across
bundle scopes), or it contains a NUL byte.

**(d) Implementation — how a rejected value is handled:**

```js
resolveEntry=ds(()=>{
  let e=Nm();if(e)return{path:e,source:void 0};
  let n=xB(),r=Lm(n.dir,!0);
  if(r)return{path:r,source:n.source};
  return{path:this.defaultPath(),source:void 0}
},()=>this.memoKey());
```

`Lm` returns `undefined` for an invalid value, so resolution falls through to `defaultPath()`.

**(e) Implementation — which settings scopes are consulted:**

```js
function xB(){let n=["policySettings","flagSettings",...tH()?["localSettings","projectSettings"]:[],"userSettings"];
for(let r of n){let s=me(r)?.autoMemoryDirectory;if(s!=null)return{dir:s,source:r}}return{dir:void 0,source:void 0}}
function tH(){if(Ce())return!0;return Yo()}
```

**(f) Env-var expansion:** a full-text search of `settings-reference.md` for `CLAUDE_PROJECT_DIR`,
"variable expansion", and "expand" returns **no** statement that settings values are expanded.
`CLAUDE_PROJECT_DIR` appears only as an environment variable handed to *hook commands* and to the
file-suggestion helper command (line 3080: "Claude Code runs the command with the same environment
variables as hooks, including `CLAUDE_PROJECT_DIR`"). The validator in (c) contains no `$`
substitution step. A literal `"${CLAUDE_PROJECT_DIR}/memory"` is therefore not absolute and is
rejected by `MB`.

`env-vars.md` lists no variable that overrides the auto-memory directory. The only env override in
the code is `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` (`function Nm(){return Lm(a.CLAUDE_COWORK_MEMORY_PATH_OVERRIDE,!1)}`),
which is undocumented, Cowork-specific, and notably passes `false` for the `~/`-expansion flag.

### Verdict: **CONFIRMED**

The constraint holds in Claude Code 2.1.274 and in the current docs, stated twice and verbatim:
"The value must be an absolute path or start with `~/`" and "**Type**: string, an absolute or
`~/`-prefixed directory path". There is no project-relative form and no `${CLAUDE_PROJECT_DIR}`
expansion. **No change needed to SKILL.md's constraint statement or to the script.**

### Findings worth carrying into the docs / backlog

1. **A bad value fails silently.** An invalid `autoMemoryDirectory` (e.g. `./memory`) is not an
   error — `Lm` returns `undefined` and Claude Code silently uses
   `~/.claude/projects/<project>/memory/` instead. *(Read from code path (c)+(d); not executed —
   I did not run a session with a deliberately broken value.)* Worth saying out loud in the README:
   "it looks like it worked, and your memory quietly goes somewhere else."

2. **`~\` is also accepted**, not just `~/` (see the `r.startsWith("~\\")` branch in (c)). The
   script only ever emits the forward-slash form, which is correct and portable. Relevant to
   backlog item 7.

3. **A stale internal description contradicts the docs — watch this.** The bundled settings schema
   describes the key as (verbatim):

   > Custom directory path for auto-memory storage. Supports ~/ prefix for home directory
   > expansion. **Ignored if set in projectSettings (checked-in .claude/settings.json) for
   > security.** When unset, defaults to ~/.claude/projects/<sanitized-cwd>/memory/.

   That is **not** what 2.1.274 actually does: `xB()` in (e) includes `projectSettings`, behind a
   `tH()` gate whose callees (`Ce`, `Yo`) I did not resolve — but the adjacent trust helpers in the
   same bundle region (`function Uge(e){...return ie().projects?.[e]?.hasTrustDialogAccepted===!0}`)
   and the docs' "same workspace trust rule as hooks" make it almost certainly the trust check.
   Either way the key is read from project settings, so the description string appears stale.
   **Risk:** the plugin's default is `--settings-file settings.json`, i.e. exactly `projectSettings`.
   If that description ever became the real behaviour, the default configuration would stop working
   and `settings.local.json` would become the only viable target. Re-check this string on future
   Claude Code releases.

4. **`permissions.blockReadsOutsideWorkingDirectories` is a documented kill-switch.** From
   `/en/memory` (verbatim): "While `permissions.blockReadsOutsideWorkingDirectories` is on, Claude
   Code loads no auto memory from a directory that a repository-supplied settings file chooses and
   saves none to it, **wherever that directory sits**." Since this plugin's whole mechanism is a
   repository-supplied settings file, turning that key on disables auto memory for the project even
   though the directory is inside the project. Default is benign — `settings-reference.md` line
   1550: "**Default**: unset, so reads outside the working directories follow your permission mode
   and rules" — so this is a caveat to document, not a blocker.

5. **SKILL.md's *rationale* for the constraint is not documented.** SKILL.md explains it as
   "Auto-memory is resolved at session startup before any working subdirectory matters, so it must
   be unambiguous." The docs give the rule but no reason. The rule is verified; the explanation is
   the author's inference. Either soften the wording or drop the causal claim.

6. **The docs describe auto memory as machine-local.** `/en/memory` (verbatim): "Auto memory is
   machine-local. All worktrees and subdirectories within the same git repository share one auto
   memory directory. Files are not shared across machines or cloud environments." That describes the
   *default* behaviour, and this plugin is precisely a way around it — but a public README should
   not read as if it contradicts official wording. Phrase it as "auto memory is machine-local by
   default; this plugin relocates it into the repo so it isn't."

7. **Adjacent mechanism worth a mention:** `CLAUDE_CODE_PROJECT_DIR_NAME` (requires v2.1.234+,
   `env-vars.md` line 339) pins the `projects/` directory name when set together with
   `CLAUDE_CONFIG_DIR`. It is a different tool — it stabilises the slug, it does not move memory
   into the repo — but it's the closest built-in alternative and also relevant to backlog item 3
   (slug derivation).

---

## Item 2 — Does `--dir-name ".claude/memory"` work as-is?

### The claim to test

Backlog item 2 states `--dir-name` "can't express a nested path" and asks whether it actually can.
The argparse help calls it a "Folder name inside the project"; the value is used at two places in
`scripts/setup_project_memory.py`:

```python
ap.add_argument("--dir-name", default="memory",                            # line 146
                help="Folder name inside the project (default: memory)")   # line 147
...
target = os.path.join(project_root, args.dir_name)                          # line 163
```

### What was checked

Executed the real script in `--dry-run` mode (no files written, no settings touched) on
Windows 11 / Python 3.12, from the repo root, plus a `posixpath.join` check for POSIX behaviour.

**Nested forward-slash name — actual output:**

```
$ python plugins/portable-memory/skills/project-local-auto-memory/scripts/setup_project_memory.py \
    --dry-run --dir-name ".claude/memory"
[dry-run] Project root : C:\Users\alice\claude-portable-memory
[dry-run] Memory target: C:\Users\alice\claude-portable-memory\.claude/memory
[dry-run] Settings file: C:\Users\alice\claude-portable-memory\.claude\settings.json
[dry-run] Migrate from : C:\Users\alice\.claude\projects\C--Users-alice-claude-portable-memory\memory  (derived)
[dry-run] No external memory to migrate; ensured target exists.
[dry-run] autoMemoryDirectory: None -> '~/claude-portable-memory/.claude/memory'
```

**Why it works.** `os.path.join` on Windows does not reject or mangle an embedded forward slash —
it only inserts a separator:

```
$ python -c "import os;print(repr(os.path.join('C:\\proj', '.claude/memory')))"
'C:\\proj\\.claude/memory'
```

The mixed-separator string is cosmetic. `to_setting_value()` calls `os.path.abspath(target)` first,
which normalises separators, then `.replace(os.sep, "/")`, so the emitted setting value is clean:
`~/claude-portable-memory/.claude/memory` — an unambiguous `~/`-prefixed path, exactly the form
item 1 confirmed as valid.

On POSIX the join is trivially correct:

```
$ python -c "import posixpath;print(posixpath.join('/home/u/proj','.claude/memory'))"
/home/u/proj/.claude/memory
```

Other variants exercised (all `--dry-run`, output trimmed to the two relevant lines):

| `--dir-name` | Memory target | Emitted `autoMemoryDirectory` | Verdict |
|---|---|---|---|
| `memory` (default) | `...\claude-portable-memory\memory` | `~/claude-portable-memory/memory` | correct |
| `.claude/memory` | `...\claude-portable-memory\.claude/memory` | `~/claude-portable-memory/.claude/memory` | **correct** |
| `.claude\memory` | `...\claude-portable-memory\.claude\memory` | `~/claude-portable-memory/.claude/memory` | correct (Windows only) |
| `.claude/memory/` | `...\claude-portable-memory\.claude/memory/` | `~/claude-portable-memory/.claude/memory` | correct (trailing slash absorbed by `abspath`) |
| `../outside` | `...\claude-portable-memory\../outside` | `~/outside` | **escapes the project, still accepted** |
| `C:/Windows/Temp/evil` | `C:/Windows/Temp/evil` | `C:/Windows/Temp/evil` | **escapes the project, still accepted** |

`.claude/memory` also looks safe as a location, with the evidence scoped to what was actually read:
per `/en/memory`, the only `.claude/` paths Claude Code loads for context are `.claude/CLAUDE.md`
and `.claude/rules/` (all `.md` discovered recursively *under `rules/`*). A `memory/` subfolder
is under neither, so it is not picked up as instructions. I did not sweep the skills / agents /
commands / plugins doc pages for other `.claude/` consumers; those use their own named
subdirectories (`skills/`, `agents/`, `commands/`), none of which is `memory/`.

### Verdict: **CONFIRMED — works as-is, no code change required**

`--dir-name ".claude/memory"` produces exactly the intended result on Windows, and the same holds
on POSIX by `posixpath.join` semantics. The backlog's premise that `--dir-name` "can't express a
nested path" is **wrong**. The real deployment using `<project>/.claude/memory` is a supported
configuration today, not a workaround.

### Recommended changes (described, deliberately NOT applied)

These are documentation/hardening improvements, not fixes for a broken feature. Nothing in this
section blocks the nested-path use case.

1. **`scripts/setup_project_memory.py:146-147` — help text undersells the flag.** Change
   `"Folder name inside the project (default: memory)"` to say a relative path is accepted, e.g.
   `"Folder (or relative path) inside the project, e.g. 'memory' or '.claude/memory' (default: memory)"`.
   Documentation only.

2. **`scripts/setup_project_memory.py:219` — the "next steps" hint is wrong for nested names.**
   The line computes `value.rsplit('/', 1)[0]`, i.e. the memory folder's *parent*, and labels it
   "clone to the SAME ~-relative path". For `--dir-name .claude/memory` it prints
   `~/claude-portable-memory/.claude`, which is not the path the user should clone to. It should
   print the project root's `~/`-relative form instead — e.g. compute it with a second
   `to_setting_value(project_root, home)` call and use that value. This is only correct today by
   accident, for the single-segment default.

3. **Reject `--dir-name` values that escape the project root.** Rows 5 and 6 of the table above show
   `--dir-name "../outside"` and an absolute `--dir-name` silently placing memory outside the
   project while still writing a valid-looking setting — which defeats the plugin's entire purpose
   (the memory no longer travels with the repo) without any warning. Suggested guard, right after
   `target = os.path.join(project_root, args.dir_name)` at line 163: reject when
   `os.path.isabs(args.dir_name)`, and reject when
   `os.path.commonpath([os.path.abspath(target), os.path.abspath(project_root)]) != os.path.abspath(project_root)`,
   exiting with a clear message. Low severity — the value is user-supplied — but a published tool
   should refuse rather than silently do the wrong thing.

4. **Backlog item 2's actual decision is still open (owner's call, not made here).** Since nested
   names already work, the choice is narrowed to: (a) keep `memory` as the default and document
   `--dir-name .claude/memory` prominently in SKILL.md and README, or (b) change the default to
   `.claude/memory` to keep the project root clean. Option (a) is non-breaking for existing
   deployments; option (b) would silently split existing setups across two directories on re-run.
   Recommendation: **(a)**, plus the help-text fix in point 1.

---

## Item 3 — What is Claude Code's real project-slug derivation?

*(Added 2026-09-18, same Claude Code build: 2.1.274.)*

### The claim

`slug_for()` described itself as replicating Claude Code's project-slug derivation by
replacing "path separators and the drive colon" — `re.sub(r"[:\\/]", "-", abspath)` — and
warned it was best-effort.

### What was checked

Extracted the derivation from the 2.1.274 bundle at `C:\Users\alice\.local\bin\claude`.

### Evidence (verbatim, minified)

```js
var F9=200;
function Le(e){return Math.abs(K9(e)).toString(36)}
function k(e){return e.replace(/[^a-zA-Z0-9]/g,"-")}
function JA(e){let n=k(e);if(n.length<=F9)return n;return`${n.slice(0,F9)}-${Le(e)}`}
function D_(e){return o6r()??JA(e)}
```

and the call site in `defaultPath()`:

```js
defaultPath(){let e=_j(),n=ei(e,"projects"),r=gn(),
m=this.canonicalWcRootForProject(r)??Yr(r)??r,
h=e===we()?D_(m):JA(m);return(ei(n,h,Lpe)+ti).normalize("NFC")}
```

### Verdict: **NEEDS CHANGE — the old regex was too narrow. Fixed.**

Three divergences, in decreasing order of how often they bite:

1. **Character class (fixed).** `k()` replaces `[^a-zA-Z0-9]` — *every* non-alphanumeric
   character, not just separators. The old regex left dots, underscores, spaces and
   non-ASCII intact, so for any such path it derived a directory that Claude Code had never
   created, and migration silently found nothing. Observed live in this repo's own session
   output: the script printed a derived source of `...Temp-tmp.HxtUbsFYfO`, where Claude
   Code would have written `...Temp-tmp-HxtUbsFYfO`. `slug_for()` now uses
   `re.sub(r"[^a-zA-Z0-9]", "-", abspath)`, pinned by tests.
2. **Truncation + hash (not reimplemented, now detected).** Over `F9 = 200` characters,
   `JA()` truncates to 200 and appends `-<base36 hash>`. The hash (`K9`) is unspecified and
   not reproducible from outside. `slug_unreliable_reason()` detects this case and the
   script warns, telling the user to pass `--source`.
3. **Environment override (not reimplemented, now detected).** `D_ = o6r() ?? JA(e)` —
   `CLAUDE_CODE_PROJECT_DIR_NAME` replaces the derived name outright (documented in
   `env-vars.md`, requires v2.1.234+). Also detected and warned about.

Note the call site picks `D_` or `JA` depending on whether the config directory is the
default — so the env override only applies in one branch. The script warns whenever the
variable is set rather than modelling that branch.

**Conclusion for the skill's guidance:** derivation is now exact for ordinary paths on
2.1.274, and *provably* inexact in two detectable cases. `--source` remains the documented
first choice, and is the only thing that is correct by construction rather than by
matching a private implementation that can change in any release.

## What remains

Backlog items 3–8 are untouched. Item 1 produced two new candidates for that list: re-checking the
stale `projectSettings`-is-ignored schema string on future releases (finding 1.3), and documenting
the `blockReadsOutsideWorkingDirectories` interaction (finding 1.4).
