"""SSH MCP Server — execute commands on remote hosts via SSH."""

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from time import time

import asyncssh
from mcp.server.fastmcp import FastMCP

logging.getLogger("asyncssh").setLevel(logging.WARNING)

mcp = FastMCP("ssh_mcp")

HOSTS_FILE = Path(__file__).parent / "hosts.json"
SESSION_TIMEOUT = 1800  # 30 minutes

# In-memory session store: {session_id: {conn, process, last_used}}
_sessions: dict[str, dict] = {}


def _load_hosts() -> dict:
    if not HOSTS_FILE.exists():
        return {}
    with open(HOSTS_FILE) as f:
        return json.load(f)


async def _connect(host_alias: str) -> asyncssh.SSHClientConnection:
    hosts = _load_hosts()
    if host_alias not in hosts:
        raise ValueError(f"Unknown host '{host_alias}'. Known: {list(hosts.keys())}")
    cfg = hosts[host_alias]
    kwargs = {"host": cfg["host"], "username": cfg.get("username", "root"), "known_hosts": None}
    if "password" in cfg:
        kwargs["password"] = cfg["password"]
    if "key" in cfg:
        kwargs["client_keys"] = [os.path.expanduser(cfg["key"])]
    return await asyncssh.connect(**kwargs)


async def _cleanup_stale():
    now = time()
    stale = [sid for sid, s in _sessions.items() if now - s["last_used"] > SESSION_TIMEOUT]
    for sid in stale:
        try:
            _sessions[sid]["conn"].close()
        except Exception:
            pass
        del _sessions[sid]


@mcp.tool()
async def ssh_list_hosts() -> dict:
    """List all configured SSH hosts (aliases, IPs, usernames — no passwords)."""
    return {alias: {"host": c["host"], "username": c.get("username", "root"), "auth": "key" if "key" in c else "password"} for alias, c in _load_hosts().items()}


@mcp.tool()
async def ssh_execute(host: str, command: str, timeout: int = 30) -> dict:
    """Run a one-shot command on a remote host. Connect, execute, return output, disconnect."""
    try:
        async with await _connect(host) as conn:
            result = await asyncio.wait_for(conn.run(command), timeout=timeout)
            return {"stdout": result.stdout.strip(), "stderr": result.stderr.strip(), "exit_code": result.exit_status}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def ssh_session_start(host: str) -> dict:
    """Open a persistent SSH session to a host. Returns a session_id for subsequent commands."""
    await _cleanup_stale()
    try:
        conn = await _connect(host)
        sid = uuid.uuid4().hex[:12]
        _sessions[sid] = {"conn": conn, "host": host, "cwd": "~", "last_used": time()}
        return {"session_id": sid, "host": host, "message": f"Session opened. Use ssh_session_command('{sid}', '<command>') to run commands."}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def ssh_session_command(session_id: str, command: str, timeout: int = 30) -> dict:
    """Run a command in an existing persistent SSH session (preserves working directory)."""
    await _cleanup_stale()
    if session_id not in _sessions:
        return {"error": f"Session '{session_id}' not found. It may have timed out."}
    s = _sessions[session_id]
    s["last_used"] = time()
    try:
        wrapped = f"cd {s['cwd']} && {{ {command}; }}; echo '___CWD___'; pwd"
        result = await asyncio.wait_for(s["conn"].run(wrapped), timeout=timeout)
        stdout = result.stdout
        if "___CWD___\n" in stdout:
            parts = stdout.rsplit("___CWD___\n", 1)
            stdout = parts[0]
            s["cwd"] = parts[1].strip()
        return {"stdout": stdout.strip(), "stderr": result.stderr.strip(), "exit_code": result.exit_status, "cwd": s["cwd"]}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def ssh_session_close(session_id: str) -> dict:
    """Close a persistent SSH session."""
    if session_id not in _sessions:
        return {"error": f"Session '{session_id}' not found."}
    try:
        _sessions[session_id]["conn"].close()
    except Exception:
        pass
    del _sessions[session_id]
    return {"status": "closed"}


if __name__ == "__main__":
    mcp.run()
