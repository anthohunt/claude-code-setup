# claude-code-setup — one set of rules, skills and mods for every Claude Code account

If you use Claude Code on several computers or with several accounts (personal, work, a second subscription),
each account has its own folder (`~/.claude`, `~/.claude-work`, …) with its own `CLAUDE.md`, `skills/` and
`settings.json`. They drift apart. This repository holds:

- `provisionner.py` — a small script that **plugs every `~/.claude*` account into the same sources**: one skills
  folder, one global `CLAUDE.md`, all your mods, an optional shared memory folder. Idempotent, silent when
  everything is in place, and it never loses an edit (see below).
- `modeles/` — a **template of global rules** (`CLAUDE.md`, in French and in English), rewritten from rules
  that proved useful: validated sends, verify before claiming, never kill by name, one question at a time,
  short answers, long tasks followed to the end.
- `machines/exemple.md` — the "machine part" pattern: what is true of *this* computer only.
- `docs/architecture.md` — how the three layers (global rules, machine part, shared memory) fit together.

> The script's comments and messages are in French.

## Requirements

Python ≥ 3.8 (standard library only), Claude Code. Linux, macOS and Windows (on Windows folder links are
junctions; file links need developer mode or elevation, otherwise the script keeps an up-to-date copy).
Only Linux was tested for this release.

## Quick start

```bash
git clone https://github.com/anthohunt/claude-code-setup.git && cd claude-code-setup
mkdir -p ~/claude-config/skills ~/claude-config/mods ~/claude-config/machines
cp modeles/CLAUDE.en.md ~/claude-config/CLAUDE.md        # or modeles/CLAUDE.md (French); edit it
cp machines/exemple.md ~/claude-config/machines/mon-ordi.md
mkdir -p ~/.config/claude-provision
cp provisionner.exemple.json ~/.config/claude-provision/config.json   # edit the paths
python3 provisionner.py --verifier     # lists what it would do (exit code 1 if something is to do)
python3 provisionner.py                # does it
```

Run it again whenever you want (cron, a systemd timer, a scheduled task, or before starting an account:
`provisionner.py --compte ~/.claude-new`). Log: `<etat>/provision.log`; last error: `<etat>/provision.error`.

## Configuration (`config.json`)

| Key | Meaning |
|---|---|
| `skills` | folder of skills, linked as `~/.claude*/skills` (an existing real `skills/` folder is moved to `<etat>/sauvegardes/` first) |
| `claude_md` | the global `CLAUDE.md`, linked as `~/.claude*/CLAUDE.md` |
| `machine_md` | optional, linked as `~/.claude-machine.md` (your `CLAUDE.md` can `@`-import it) |
| `mods` | optional, folder with one folder per mod (`<mod>/.claude-plugin/plugin.json`); all are put in `CLAUDE_CODE_PLUGIN_DIRS`. A `retenus.json` `{"retenus": {"mod": "reason"}}` sets mods aside |
| `etat` | where the log, backups and fingerprints live |
| `memoire` | optional, `autoMemoryDirectory` shared by all accounts |
| `plafond_skills` | optional, `SLASH_COMMAND_TOOL_CHAR_BUDGET` (see below) |
| `exclus` | account folders never touched |
| `isoles` | accounts that must **not** share rules or memory (see below) |

Relative paths are relative to the config file. `~` and `$VARS` are expanded.

## What it guarantees, and what it will not do

- **No edit is lost.** `CLAUDE.md` is a link. Where links are refused, the account gets a copy; if you edit that
  copy, the change is copied *back* into the global file instead of being overwritten. If both changed, the
  account's version is saved to `<etat>/sauvegardes/` and an error is reported.
- **`settings.json` is merged, never replaced**: only `env.CLAUDE_CODE_PLUGIN_DIRS`, optionally
  `env.SLASH_COMMAND_TOOL_CHAR_BUDGET` and `autoMemoryDirectory` are set; a backup is made before the first change.
  Plugin directories that are *not* inside your mods folder are kept.
- **The skills budget.** By default Claude Code lists skills within about 1% of the context window and drops the
  descriptions of the least used ones when there are many, so it can no longer pick them. `plafond_skills` raises
  that budget to a fixed number of characters.
- **Isolated accounts.** An account provided by an employer should not see your personal rules or memory. An entry of
  `isoles` (`dossier`: a word of the folder name, or `courriel`: the end of the account's e-mail address) gets its own
  `claude_md` (or none), no shared memory, and `claudeMdExcludes` for the global file. This is a convenience, not a
  security boundary: keep real secrets out of the rules.
- Other settings, credentials and history are never read or modified. Accounts are only found in `~/.claude*`
  folders that contain `.credentials.json`, `settings.json` or `projects/`.

## Tests

```bash
python3 -m unittest discover -s tests -v     # runs in a throw-away HOME, touches no real account
```

## Licences

- Code (`provisionner.py`, tests): [Apache License 2.0](LICENSE), see [NOTICE](NOTICE).
- Rules templates, machine example, documentation: [Creative Commons Attribution 4.0](LICENSE-docs).
- No third-party code is included.

---

**Anthony Hunt** · [Project page on ingevision.cloud](https://ingevision.cloud/?lang=en&p=outils-claude-code) · [LinkedIn](https://www.linkedin.com/in/anthony-hunt-3948a9196) · [GitHub profile](https://github.com/anthohunt)
