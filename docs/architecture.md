# Three layers: global rules, machine part, shared memory

```
              ┌──────────────────────── CLAUDE.md (global, one file) ───────────────────────┐
 every        │ stable, critical rules ([!] = never break). Imports:  @~/.claude-machine.md  │
 account ───▶ └──────────────────────────────────────────────────────────────────────────────┘
 (~/.claude*)            │                                   │
                         ▼                                   ▼
            ~/.claude-machine.md                     autoMemoryDirectory
            what is true of THIS computer:           what Claude learned from your
            paths, tools, limits, how to log in      corrections: one small file per fact,
            (one file per computer)                  shared by all accounts
```

**Global rules** change rarely and only when you say so. They are the rules you would repeat in every new
conversation. Keep them short: every line is read at the start of every session.

**Machine part**: the same rules are true on your laptop and on your server, but paths, installed tools and
limits are not. A computer-specific file, imported with `@~/.claude-machine.md`, keeps the global file identical
everywhere. `provisionner.py` links it to `~/.claude-machine.md`.

**Shared memory** is Claude Code's automatic memory (`autoMemoryDirectory` in `settings.json`), pointed at one
folder that all your accounts use — typically a folder of a git repository you sync between your computers. The
rule "when the user corrects or states a preference, save it right away and say 'Noted: …'" lives in the global
file; the memory itself is a set of small Markdown files with a front-matter (`name`, `description`, `type`)
and an index file. If a memory contradicts the global file, the global file wins.

**Why a script and not a symlink by hand?** Because accounts appear (a new login creates a new `~/.claude-x`),
because Windows refuses links without privileges, because an account's `settings.json` must be merged without
touching the other settings, and because an edit made in an account must not be lost. `provisionner.py` handles
those cases and is safe to run every minute.

**Isolated accounts** (an employer's account, a client's) must not receive your personal rules or memory. Claude
Code treats `~/.claude/settings.json` and `~/.claude/CLAUDE.md` as *project* files for anything started in your home
folder, and a project file takes precedence over user settings: so an isolated account cannot simply override the
shared memory or rules — the script switches its automatic memory off and adds the global file to
`claudeMdExcludes`.
