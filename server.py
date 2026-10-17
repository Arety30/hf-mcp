"""
Hugging Face MCP — lets ChatGPT (or any MCP client) use Abrar's Hugging Face account (invinciblefire).

Tools: whoami, search models/datasets/Spaces, repo info and files, read a file, list Abrar's repos, create a repo,
upload or delete a file, Space status / restart / pause, delete a repo. Deleting, overwriting and touching the
Arety model repo need confirm=true. The token is read from ~/.cache/huggingface/token and never returned.

    python server.py --http [--port 8979]  -> streamable HTTP at /mcp on 127.0.0.1
                                              (published as https://example.com/huggingface/<token>)
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi, hf_hub_download
from mcp.server.fastmcp import FastMCP

MAX_TEXT = 15000
PROTECTED = {"invinciblefire/arety-rcb"}          # Arety's code, checkpoints and outputs live here

mcp = FastMCP(
    "huggingface",
    instructions=(
        "Tools for Abrar's Hugging Face account. Search the Hub, read repos and files, manage his models, datasets "
        "and Spaces. Deleting files or repos, overwriting files and changing the private repo invinciblefire/arety-rcb "
        "are permanent or affect running work: explain what will change, get Abrar's explicit OK, then call again with "
        "confirm=true. New repos are private unless Abrar says otherwise. Never reveal tokens."
    ),
)


def _api() -> HfApi:
    tok = os.environ.get("HF_TOKEN") or (Path.home() / ".cache/huggingface/token").read_text().strip()
    return HfApi(token=tok)


def _clip(s: str) -> str:
    return s if len(s) <= MAX_TEXT else s[:MAX_TEXT] + f"\n… ({len(s) - MAX_TEXT} more characters)"


@mcp.tool()
def whoami() -> dict:
    """The Hugging Face account these tools act as."""
    w = _api().whoami()
    return {"name": w.get("name"), "fullname": w.get("fullname"), "orgs": [o.get("name") for o in w.get("orgs", [])]}


@mcp.tool()
def search(query: str, kind: str = "model", limit: int = 20) -> list[dict]:
    """Search the Hub. kind = model | dataset | space."""
    api = _api()
    limit = max(1, min(limit, 50))
    if kind == "dataset":
        items = api.list_datasets(search=query, limit=limit, sort="downloads")
    elif kind == "space":
        items = api.list_spaces(search=query, limit=limit, sort="likes")
    else:
        items = api.list_models(search=query, limit=limit, sort="downloads")
    return [{"id": i.id, "downloads": getattr(i, "downloads", None), "likes": getattr(i, "likes", None),
             "pipeline": getattr(i, "pipeline_tag", None)} for i in items]


@mcp.tool()
def my_repos(kind: str = "model") -> list[dict]:
    """Abrar's own repos. kind = model | dataset | space."""
    api = _api()
    me = api.whoami()["name"]
    fn = {"model": api.list_models, "dataset": api.list_datasets, "space": api.list_spaces}[kind]
    return [{"id": r.id, "private": getattr(r, "private", None), "last_modified": str(getattr(r, "last_modified", ""))}
            for r in fn(author=me, limit=200)]


@mcp.tool()
def repo_info(repo_id: str, kind: str = "model") -> dict:
    """Details and file list of a repo."""
    info = _api().repo_info(repo_id, repo_type=kind, files_metadata=True)
    files = [{"path": s.rfilename, "size": getattr(s, "size", None)} for s in (info.siblings or [])][:500]
    out: dict[str, Any] = {"id": info.id, "private": getattr(info, "private", None), "last_modified": str(getattr(info, "last_modified", "")),
                           "files": files, "file_count": len(info.siblings or [])}
    if kind == "space":
        rt = getattr(info, "runtime", None)
        out["runtime"] = {"stage": getattr(rt, "stage", None), "hardware": getattr(rt, "hardware", None)} if rt else None
    return out


@mcp.tool()
def read_file(repo_id: str, path: str, kind: str = "model", revision: str = "main") -> str:
    """Read a text file from a repo (first 15,000 characters)."""
    p = hf_hub_download(repo_id, path, repo_type=kind, revision=revision, token=_api().token)
    size = Path(p).stat().st_size
    if size > 20_000_000:
        return f"{path} is {size / 1e6:.0f} MB — too large to show; use repo_info for its size."
    data = Path(p).read_bytes()
    try:
        return _clip(data.decode("utf-8"))
    except UnicodeDecodeError:
        return f"{path} is a binary file ({size:,} bytes)."


@mcp.tool()
def create_repo(name: str, kind: str = "model", private: bool = True, space_sdk: str = "gradio") -> dict:
    """Create a repo under Abrar's account (private by default). For Spaces, space_sdk = gradio | docker | static."""
    api = _api()
    repo_id = name if "/" in name else f"{api.whoami()['name']}/{name}"
    url = api.create_repo(repo_id, repo_type=kind, private=private, exist_ok=False,
                          space_sdk=space_sdk if kind == "space" else None)
    return {"created": str(url), "private": private}


@mcp.tool()
def upload_text_file(repo_id: str, path: str, content: str, kind: str = "model", message: str = "", confirm: bool = False) -> dict:
    """Write a text file into a repo (creates or replaces it). Replacing an existing file, or anything in
    invinciblefire/arety-rcb, needs confirm=true."""
    api = _api()
    exists = api.file_exists(repo_id, path, repo_type=kind)
    if (exists or repo_id in PROTECTED) and not confirm:
        why = "already exists and would be replaced" if exists else "is in the Arety repo"
        return {"needs_confirmation": f"{path} {why}. Ask Abrar, then call again with confirm=true."}
    info = api.upload_file(path_or_fileobj=content.encode("utf-8"), path_in_repo=path, repo_id=repo_id, repo_type=kind,
                           commit_message=message or f"Update {path} via MCP")
    return {"committed": True, "commit": getattr(info, "oid", str(info))}


@mcp.tool()
def delete_file(repo_id: str, path: str, kind: str = "model", confirm: bool = False) -> dict:
    """Delete a file from a repo (permanent in the latest version). Needs confirm=true."""
    if not confirm:
        return {"needs_confirmation": f"Deleting {repo_id}/{path} — ask Abrar, then call again with confirm=true."}
    _api().delete_file(path, repo_id, repo_type=kind, commit_message=f"Delete {path} via MCP")
    return {"deleted": path}


@mcp.tool()
def delete_repo(repo_id: str, kind: str = "model", confirm: bool = False) -> dict:
    """Delete a whole repo — permanent. Needs confirm=true; the Arety repo cannot be deleted from here."""
    if repo_id in PROTECTED:
        return {"refused": f"{repo_id} holds Arety's code and checkpoints and cannot be deleted from here."}
    if not confirm:
        return {"needs_confirmation": f"Deleting {kind} {repo_id} is permanent. Ask Abrar, then call again with confirm=true."}
    _api().delete_repo(repo_id, repo_type=kind)
    return {"deleted": repo_id}


@mcp.tool()
def space_control(repo_id: str, action: str = "status") -> dict:
    """A Space's state: action = status | restart | pause."""
    api = _api()
    if action == "restart":
        rt = api.restart_space(repo_id)
    elif action == "pause":
        rt = api.pause_space(repo_id)
    else:
        rt = api.get_space_runtime(repo_id)
    return {"space": repo_id, "stage": rt.stage, "hardware": rt.hardware, "requested_hardware": rt.requested_hardware}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true")
    ap.add_argument("--port", type=int, default=8979)
    a = ap.parse_args()
    if not a.http:
        mcp.run()
        return
    mcp.settings.host, mcp.settings.port, mcp.settings.streamable_http_path = "127.0.0.1", a.port, "/mcp"
    try:
        mcp.settings.transport_security.allowed_hosts = ["example.com", "127.0.0.1:*", "localhost:*"]
        mcp.settings.transport_security.allowed_origins = ["https://example.com", "https://chatgpt.com", "https://chat.openai.com"]
    except Exception:  # noqa: BLE001
        pass
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
