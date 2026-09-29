from pathlib import Path

from pydantic import BaseModel


class PullRequestTarget(BaseModel):
    owner: str
    repo: str
    base_branch: str = "main"
    head_branch: str
    subdirectory: str = ""


async def open_pull_request(
    token: str, target: PullRequestTarget, tree: Path, title: str, body: str
) -> str:
    """TODO: create a branch, commit the export tree via the GitHub API, open a PR, return its URL.

    Never merge (FR-19). Reuse the existing PR if head_branch already has one.
    """
    raise NotImplementedError
