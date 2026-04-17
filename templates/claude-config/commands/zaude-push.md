Push any local framework edits back to the Zaude repo as a reviewable pull request. Never commits directly to main. The genericization lint runs before anything reaches GitHub — if private markers are detected, nothing is pushed.

## What this command does

1. Invokes `~/zaude/install/zaude-sync.sh` (or wherever `zaude_repo_path` in `~/.zaude/config.json` points to Zaude's clone).
2. The script:
   - Collects your local framework files (hooks, commands, settings.json, global CLAUDE.md, vault patterns)
   - Diffs them against the Zaude repo's `origin/main`
   - Runs the genericization lint on the diff (checks added content for private markers from the default list plus your `sync_private_markers` config)
   - If the lint passes AND changes exist, creates a branch `sync-YYYY-MM-DD-HHMMSS`, commits, pushes, opens a PR via `gh`
   - If the lint fails, aborts with a report of what markers were found
   - If nothing changed, exits quietly

## When to use

- After you've iterated on a hook, slash command, or pattern file locally during a project session and want the improvement back in Zaude.
- Before ending a session in which you edited framework files (alternative: set `auto_sync: true` in config for `/wrap` to trigger this automatically).
- When you want to propose a framework change for community review.

## Flow

1. Run the script in `--lint-only` mode first and report the result to the user. If the lint fails, report each offending line with its marker and stop — do NOT offer to push. The user has to either fix the content or add an allow-list entry before proceeding.

2. If the lint passes, run the script in `--dry-run` mode and show the user a summary of what will be synced (file count, file names, one-line diff preview).

3. Ask the user to confirm: "Create a sync PR on the Zaude repo? [y/n]"

4. If yes, run the script in `--yes` mode. Relay the PR URL the script outputs so the user can open it on GitHub.

5. If no, stop. Nothing is pushed.

## Gates

- **Lint must pass.** If the genericization lint finds private markers (company name, internal IPs, project slugs from the default list + user's `sync_private_markers`), STOP. Report what was found. Do NOT try to "clean up" the content automatically — the user must decide whether to edit the file, add a marker exception, or exclude the path.
- **PR-only.** This command never pushes directly to `main`. It only creates branches.
- **No unrelated content.** If the script would stage files beyond the known framework targets (hooks, commands, settings.json, global CLAUDE.md, patterns), report it and stop — that's a bug in the detection logic.

## Arguments

None. The command reads from `~/.zaude/config.json`.

## On failure

If the script exits with code 2 (lint failed), the user's options:
1. Edit the offending file to remove the private marker.
2. Add the marker to `sync_private_markers` in `~/.zaude/config.json` as an ALLOWED token (not a blocked one — the config lists BLOCKED markers; if a legitimate token happens to match a default blocker, the user would need to exclude the file via `sync_exclude` instead).
3. Add the file path to `sync_exclude` in `~/.zaude/config.json` to skip it permanently.

If the script exits with code 3 (git/gh error), surface the error message to the user and suggest they check:
- `gh auth status` (must be authenticated)
- `git status` in the Zaude repo (must be clean — no uncommitted changes)
- `git fetch origin` works (network / repo access)

## After the PR opens

- The user reviews the PR on GitHub.
- When they merge, the change ships to `main` and becomes the canonical template for future Zaude installs.
- On the user's next Zaude-repo `git pull`, their local clone reflects the change.
- Other Zaude users see the improvement on their next install or upgrade.
