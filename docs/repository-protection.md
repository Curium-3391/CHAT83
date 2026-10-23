# CHAT83 repository protection — administrator setup

> **Important:** The JSON files in this directory are **ready-to-import templates**, NOT live GitHub rules. Committing these files does not activate protection. This document must not be interpreted as a claim that `main` or `v*` are protected. Activate them in GitHub **Settings → Rules → Rulesets**, then verify the branch state.

## Current intent

- **Current visibility: Public (owner-approved, verified 2026-10-23).** The v0.6.0 release, repository source and Git history are now publicly accessible. Switching visibility to public does not replace active branch/tag rulesets. Review all historic commits for credentials before treating public exposure as fully audited.
- Protect `main` from deletion, force pushes and direct changes without a pull request.
- Require all four existing GitHub Actions jobs to succeed before merging: `python`, `z80`, `uno`, `link-handshake-mock`. The CI workflow was updated in PR #16 to run even on documentation-only pull requests.
- Require resolution of review conversations. Set **zero mandatory independent approvals** while there is only one active maintainer; enable one reviewer after another trusted contributor is available.
- Keep `v*` tags immutable **after creation** (no deletion or rewriting). Allow creation of the next version tag without granting standing bypass permissions.
- Do not require linear history: the repository currently uses GitHub's merge commits for PRs.
- Rulesets use **Active** enforcement and **no bypass actors**. This includes administrators; assess any deployment automation before changing release tags.

## Plan / permission prerequisites

According to [GitHub's ruleset documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository), **private repository rulesets** require GitHub Pro, GitHub Team or GitHub Enterprise Cloud. If the owner's account is on GitHub Free, a private repository cannot enforce these rules until the plan is upgraded. **Do not make the repository public just to enable rulesets** without first reviewing the repository history, artifacts and secrets.

The ChatGPT GitHub connector's available operations **do not include repository Administration writes**. Even when the logged-in account has `admin` repository permissions, the connected GitHub App cannot create/edit rulesets through that connection. These files were prepared without elevated or personal-access-token workarounds.

## Import: main branch

1. Download [CHAT83-main-branch.json](rulesets/CHAT83-main-branch.json) to your PC using GitHub's file **Download raw file** control.
2. Open [CHAT83 Rulesets settings](https://github.com/Curium-3391/CHAT83/settings/rules).
3. Select **New ruleset → Import a ruleset**, choose that local JSON.
4. Confirm **Target: Branch**, **Target includes: `main`**, **Enforcement: Active**, **Bypass actors: none**.
5. Confirm **Require a pull request** (0 required approvals), **Require conversation resolution**, **Block force pushes**, **Restrict deletions**.
6. Confirm these **four exact required checks** (not the workflow display name): `python`, `z80`, `uno`, `link-handshake-mock`. Require branch to be up to date with `main`.
7. Review and click **Create**.

The `package` job is intentionally not required; the four core jobs gate merges, and packaging remains part of release verification.

## Import: version tags

1. Download [CHAT83-version-tags.json](rulesets/CHAT83-version-tags.json).
2. In the same Rulesets screen, select **New ruleset → Import a ruleset**.
3. Confirm **Target: Tag**, **Include: `v*`**, **Enforcement: Active**, **No bypass**, **Restrict deletions**, **Block force pushes**.
4. **Do not enable Restrict creations:** subsequent release versions need to be able to create a new tag.
5. Click **Create**.

Existing tag `v0.6.0` is intended to be protected as well; the ruleset does not retroactively alter its commit.

## Verify after activation

- [ ] [Repository Rulesets](https://github.com/Curium-3391/CHAT83/settings/rules) shows **two Active rulesets**.
- [ ] [`main` branch](https://github.com/Curium-3391/CHAT83/branches) appears protected.
- [ ] A test documentation PR runs all four jobs and cannot merge before required checks pass.
- [ ] The `v*` tag rule shows deletion and rewriting restricted; future new tags are still allowed.
- [ ] Repository visibility is **Public**, and both the `main` branch and `v*` rulesets remain **Active** after the visibility change.
- [ ] [Actions settings](https://github.com/Curium-3391/CHAT83/settings/actions) default workflow permissions are least-privilege (read-only when possible); the release workflow explicitly requests `contents: write` for publishing.
- [ ] Review [GitHub security settings](https://github.com/Curium-3391/CHAT83/settings/security_analysis) for available secret scanning/push protection, especially before considering public visibility.
- [ ] Any previously disclosed `GEMINI_API_KEY` has been **revoked** and replaced. `.gitignore` cannot undo exposure of a key already shared or committed.

**Important caution:** After importing a strict, no-bypass ruleset, automated release workflows or administrator direct writes to `main` may be rejected. Use PRs and green CI. If a workflow must commit to a protected branch in the future, redesign it to propose a PR instead of weakening protection.

## Public release verification (2026-10-23)

The user authorized a public release of the repository. A subsequent GitHub API check reported `private=false`, `visibility=public`, `main.protected=true` and both rulesets `enforcement=active`.

A pattern-based scan of the **56 tracked files in current `main`** detected no common Google/OpenAI/GitHub credential strings or private key headers. This is **not** a complete history scan, so it does not certify that earlier commits or deleted files never held credentials. Sampled commit metadata includes non-`noreply` author email addresses, which are public as part of Git history. Revoke and rotate any Gemini API key previously pasted into chat or logs, even if it never appeared in the repository.

## Notes on what these rules cannot do

Rulesets do not erase secrets from Git history, protect a previously disclosed Gemini key, or guarantee there are no vulnerabilities in the code. They are repository governance controls, not a replacement for code review and secret-scanning. The calculator/Uno communications also remain subject to their documented experimental hardware timing limitations.
