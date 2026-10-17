# hf-mcp

A single-file Model Context Protocol (MCP) server by Syed Abrar Ali that lets an MCP client (a chat assistant, an IDE agent or any MCP-capable tool) work with one Hugging Face account: search the Hub, inspect repositories and read their files, create repos, upload or delete files, and check, restart or pause Spaces. The problem it solves is giving an assistant useful Hub access without ever showing it the access token, and making sure the few actions that are permanent or that touch running work (deleting, overwriting, editing a protected repo) cannot happen without an explicit `confirm=true` after a human has agreed.

## Where it is used

It runs on the owner's laptop alongside a few other personal MCP servers. In HTTP mode it binds only to the loopback interface and a reverse-proxy gateway publishes it under a secret path so a remote chat assistant can use it as a connector. In stdio mode local MCP clients launch it directly. Its typical job is day-to-day Hub housekeeping: finding models and datasets, reading model cards and configs, pushing small text files (READMEs, configs) into the owner's repos and checking whether a Space is running.

## How it works

Everything is in `server.py`, built on `mcp.server.fastmcp.FastMCP` and the official `huggingface_hub` client.

| Piece | Role |
| --- | --- |
| `_api()` | Builds an `HfApi` with the token from `HF_TOKEN` or, failing that, `~/.cache/huggingface/token` (the file written by `hf auth login`). The token is never returned to the client. |
| `PROTECTED` | A set of repo ids that hold important work. Writing into them needs `confirm=true`; deleting them is refused outright. |
| `_clip()` | Truncates text results to 15,000 characters. |
| `mcp = FastMCP("huggingface", instructions=...)` | Server instructions: read freely, new repos are private by default, explain and get an explicit OK before deleting or overwriting, never reveal tokens. |
| `main()` | Chooses stdio or streamable-HTTP transport. |

Tools:

| Tool | What it does | Guard |
| --- | --- | --- |
| `whoami` | Account name, full name and organisations | — |
| `search(query, kind, limit)` | Hub search for `model` (sorted by downloads), `dataset` (downloads) or `space` (likes); up to 50 results | — |
| `my_repos(kind)` | The account's own models, datasets or Spaces (up to 200) | — |
| `repo_info(repo_id, kind)` | Privacy flag, last modified, file list with sizes (first 500); for Spaces also the runtime stage and hardware | — |
| `read_file(repo_id, path, kind, revision)` | Downloads the file with `hf_hub_download` and returns the first 15,000 characters; refuses files above 20 MB and reports binaries instead of dumping them | — |
| `create_repo(name, kind, private, space_sdk)` | Creates a model/dataset/Space under the account; Spaces take `gradio`, `docker` or `static` | — |
| `upload_text_file(repo_id, path, content, kind, message)` | Commits a UTF-8 text file | `confirm=true` if the file already exists or the repo is protected |
| `delete_file(repo_id, path, kind)` | Deletes a file in a new commit | `confirm=true` |
| `delete_repo(repo_id, kind)` | Deletes a whole repo | `confirm=true`; refused for protected repos |
| `space_control(repo_id, action)` | `status`, `restart` or `pause` a Space; returns stage, hardware and requested hardware | — |

Decision rule: a guarded call without `confirm=true` returns `{"needs_confirmation": "..."}` describing what would change rather than raising, so the model can relay it and retry after approval. Nothing is stored locally except what `huggingface_hub` caches on download.

## Setup

Requirements:

- Python 3.10 or newer
- `mcp` and `huggingface_hub` (`pip install "mcp[cli]" huggingface_hub`)
- a Hugging Face token with write access, either logged in with `hf auth login` (stored in `~/.cache/huggingface/token`) or exported as `HF_TOKEN`

```bash
git clone https://github.com/USER/hf-mcp.git
cd hf-mcp
python -m venv .venv && . .venv/bin/activate
pip install "mcp[cli]" huggingface_hub
```

Configuration:

| Setting | Where | Meaning |
| --- | --- | --- |
| `HF_TOKEN` | environment (optional) | Overrides the token file. |
| `PROTECTED` | constant in `server.py` | Set of `"user/repo"` ids that must not be deleted and need confirmation to write; replace with your own. |
| `MAX_TEXT` | constant | Result truncation length (15000). |
| `transport_security.allowed_hosts/origins` | in `main()` | Hostnames and origins allowed to reach the HTTP transport; put your gateway hostname here (for example `mcp.example.com`). |

## Usage

Stdio:

```bash
python server.py
```

Client configuration example:

```json
{ "mcpServers": { "huggingface": { "command": "python", "args": ["~/hf-mcp/server.py"] } } }
```

Streamable HTTP behind a reverse proxy:

```bash
python server.py --http --port 8979
# serves http://127.0.0.1:8979/mcp
```

Example interactions:

- "Find small instruction-tuned models for summarisation" → `search(query="summarization instruct", kind="model")`
- "Show the config.json of USER/my-model" → `read_file(repo_id="USER/my-model", path="config.json")`
- "Create a private dataset repo called notes" → `create_repo(name="notes", kind="dataset")`
- "Update the README of my-model" → `upload_text_file(...)` returns `needs_confirmation` because the file exists; after approval the client repeats the call with `confirm=true`
- "Is my demo Space up? Restart it." → `space_control("USER/demo")`, then `space_control("USER/demo", action="restart")`

## Project structure

```
hf-mcp/
└── server.py     # FastMCP server: HfApi helpers, 10 tools, stdio/HTTP entry point
```

## Limitations and notes

- Only text files can be uploaded, and only one per commit; binary uploads and folder uploads are out of scope.
- `read_file` downloads the full file into the local Hugging Face cache before clipping it, so very large text files cost disk space (files above 20 MB are refused).
- Spaces can be created, inspected, restarted and paused, but not given different hardware or secrets from here.
- The HTTP transport has no authentication of its own; it binds to the loopback interface and expects a fronting proxy with a secret path and TLS.
- `delete_file` and `delete_repo` are permanent on the Hub; the confirmation flag is the only safeguard.
- Server instructions and confirmation messages refer to the owner by first name; edit them if you deploy the server for someone else.
