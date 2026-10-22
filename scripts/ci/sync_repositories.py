"""Mirror authoritative GitGud history to GitHub; never write to GitGud."""
import argparse
import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path


class SyncError(RuntimeError):
    pass


def git(directory, *arguments, check=True):
    result = subprocess.run(
        ["git", "-C", str(directory), *arguments],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if check and result.returncode:
        # Do not echo remote URLs or credential-bearing arguments.
        raise SyncError(f"git {arguments[0]} failed (exit {result.returncode})")
    return result


def merge_upstream(directory, heads, branch):
    """Merge the authoritative branch into the mirror, rewriting neither side.

    A merge commit is the only way to keep mirror-local CI definitions while
    still taking every upstream commit. Nothing is forced: the merge commit is
    built in a throwaway worktree and pushed as a fast-forward of the mirror.
    """
    worktree = Path(directory) / "merge-worktree"
    git(directory, "worktree", "add", "--quiet", "-B", "sync-merge", str(worktree), "refs/sync/github")
    git(worktree, "config", "user.name", "Repository sync")
    git(worktree, "config", "user.email", "repository-sync@users.noreply.github.com")
    message = f"Merge authoritative upstream {heads['upstream'][:12]} into {branch}"
    merged = git(worktree, "merge", "--no-ff", "-m", message, "refs/sync/upstream", check=False)
    if merged.returncode:
        conflicts = git(worktree, "diff", "--name-only", "--diff-filter=U", check=False).stdout.split()
        git(worktree, "merge", "--abort", check=False)
        detail = f" in {', '.join(sorted(set(conflicts)))}" if conflicts else ""
        raise SyncError(
            f"Merge conflict with authoritative upstream{detail}; resolve it through an upstream MR. "
            "Neither remote was changed"
        )
    return git(worktree, "rev-parse", "HEAD").stdout.strip()


def synchronize(github, upstream, branch="master", apply=False, merge=False):
    with tempfile.TemporaryDirectory(prefix="servers5a3-sync-") as temporary:
        git(temporary, "init", "--bare", "--quiet")
        if git(temporary, "check-ref-format", "--branch", branch, check=False).returncode:
            raise SyncError("Invalid branch name")
        reference = f"refs/heads/{branch}"
        for name, url in (("github", github), ("upstream", upstream)):
            git(temporary, "remote", "add", name, url)
            git(temporary, "fetch", "--no-tags", name, f"{reference}:refs/sync/{name}")
        heads = {name: git(temporary, "rev-parse", f"refs/sync/{name}").stdout.strip()
                 for name in ("github", "upstream")}
        result = {"branch": branch, "before": heads, "applied": False, "direction": "equal"}
        if heads["github"] == heads["upstream"]:
            return result
        if git(temporary, "merge-base", "--is-ancestor", heads["github"], heads["upstream"], check=False).returncode == 0:
            # CI definitions are reviewed in the authoritative upstream MR, just like
            # other source. Execute only this checked-out script, never fetched code.
            result["direction"] = "upstream-to-github"
            result["commit"] = heads["upstream"]
            if apply:
                for name in ("github", "upstream"):
                    observed = git(temporary, "ls-remote", "--exit-code", name, reference).stdout.split()[0]
                    if observed != heads[name]:
                        raise SyncError("Remote changed before synchronization; retry with a fresh snapshot")
                # No force flag: an intervening destination commit is rejected by receive-pack.
                git(temporary, "push", "github", f"{heads['upstream']}:{reference}")
                observed = {}
                for name in ("github", "upstream"):
                    output = git(temporary, "ls-remote", "--exit-code", name, reference).stdout
                    observed[name] = output.split()[0]
                result["after"] = observed
                result["applied"] = True
                if observed["github"] != observed["upstream"]:
                    raise SyncError("Remote changed during synchronization; fetch again on the next run")
            return result
        if not merge:
            raise SyncError("GitHub is ahead or diverged; submit its changes by MR to authoritative GitGud. Neither remote was changed")
        if git(temporary, "merge-base", "--is-ancestor", heads["upstream"], heads["github"], check=False).returncode == 0:
            # Mirror holds commits upstream does not have yet (its own CI definitions)
            # and upstream has nothing new, so there is nothing to merge.
            result["direction"] = "github-ahead"
            return result
        result["direction"] = "merge-upstream"
        result["commit"] = heads["upstream"]
        if apply:
            merged = merge_upstream(temporary, heads, branch)
            for name in ("github", "upstream"):
                observed = git(temporary, "ls-remote", "--exit-code", name, reference).stdout.split()[0]
                if observed != heads[name]:
                    raise SyncError("Remote changed before synchronization; retry with a fresh snapshot")
            # Non-force push: a concurrent commit on the mirror rejects this merge.
            git(temporary, "push", "github", f"{merged}:{reference}")
            observed = git(temporary, "ls-remote", "--exit-code", "github", reference).stdout.split()[0]
            if observed != merged:
                raise SyncError("GitHub did not accept the merge commit; check branch protection on the mirror")
            result["after"] = {"github": observed, "upstream": heads["upstream"]}
            result["applied"] = True
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github", required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--branch", default="master")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--merge", action="store_true",
                        help="Keep mirror-local commits (CI definitions) and merge upstream into them instead of stopping")
    args = parser.parse_args()
    token = os.environ.pop("GH_SYNC_TOKEN", "")
    if token:
        # URL-scoped config prevents forwarding GitHub credentials to GitGud.
        encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        os.environ.update({
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {encoded}",
        })
    try:
        result = synchronize(args.github, args.upstream, args.branch, args.apply, args.merge)
    except SyncError as error:
        print(f"Synchronization stopped: {error}")
        raise SystemExit(1)
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as output:
            output.write(f"```json\n{rendered}\n```\n")


if __name__ == "__main__":
    main()
