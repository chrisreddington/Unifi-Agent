"""SSH MCP Server — execute commands on remote hosts via SSH.

Uses the system SSH configuration (~/.ssh/config, ~/.ssh/known_hosts,
ssh-agent) for host resolution, authentication, and host key verification.
"""

import asyncio
import atexit
import logging
import re
import uuid
from time import time

import asyncssh
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("ssh_mcp")
logging.getLogger("asyncssh").setLevel(logging.WARNING)

mcp = FastMCP("ssh_mcp")

SESSION_TIMEOUT = 1800  # 30 minutes
MAX_SESSIONS = 10

# In-memory session store: {session_id: {conn, host, cwd, last_used}}
_sessions: dict[str, dict] = {}

# Only allow safe path characters to prevent command injection via cwd
_SAFE_PATH_RE = re.compile(r"^[a-zA-Z0-9/_\-.~]+$")


def _validate_path(path: str) -> str:
    """Validate a path contains only safe characters."""
    if not path or not _SAFE_PATH_RE.match(path):
        raise ValueError(f"Invalid path: contains unsafe characters")
    if ".." in path.split("/"):
        raise ValueError(f"Invalid path: directory traversal not allowed")
    return path


async def _connect(host: str) -> asyncssh.SSHClientConnection:
    """Connect using system SSH config (~/.ssh/config, known_hosts, ssh-agent)."""
    return await asyncssh.connect(host)


async def _cleanup_stale():
    now = time()
    stale = [sid for sid, s in _sessions.items() if now - s["last_used"] > SESSION_TIMEOUT]
    for sid in stale:
        try:
            _sessions[sid]["conn"].close()
        except Exception as e:
            logger.warning("Failed to close stale session %s: %s", sid, e)
        del _sessions[sid]


def _cleanup_all():
    """Close all sessions on shutdown."""
    for sid, s in list(_sessions.items()):
        try:
            s["conn"].close()
        except Exception as e:
            logger.warning("Failed to close session %s on shutdown: %s", sid, e)
    _sessions.clear()


atexit.register(_cleanup_all)


@mcp.tool()
async def ssh_execute(host: str, command: str, timeout: int = 30) -> dict:
    """Run a one-shot command on a remote host. Connect, execute, return output, disconnect.
    Uses ~/.ssh/config for host resolution and authentication."""
    try:
        async with await _connect(host) as conn:
            result = await asyncio.wait_for(conn.run(command), timeout=timeout)
            return {"stdout": result.stdout.strip(), "stderr": result.stderr.strip(), "exit_code": result.exit_status}
    except asyncssh.Error as e:
        return {"error": f"SSH error: {e}"}
    except asyncio.TimeoutError:
        return {"error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def ssh_session_start(host: str) -> dict:
    """Open a persistent SSH session to a host. Returns a session_id for subsequent commands.
    Uses ~/.ssh/config for host resolution and authentication."""
    await _cleanup_stale()
    if len(_sessions) >= MAX_SESSIONS:
        return {"error": f"Maximum number of sessions ({MAX_SESSIONS}) reached. Close an existing session first."}
    try:
        conn = await _connect(host)
        sid = uuid.uuid4().hex[:12]
        _sessions[sid] = {"conn": conn, "host": host, "cwd": "~", "last_used": time()}
        return {"session_id": sid, "host": host, "message": f"Session opened. Use ssh_session_command('{sid}', '<command>') to run commands."}
    except asyncssh.Error as e:
        return {"error": f"SSH error: {e}"}
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
        cwd = _validate_path(s["cwd"])
        wrapped = f"cd {cwd} && {{ {command}; }}; echo '___CWD___'; pwd"
        result = await asyncio.wait_for(s["conn"].run(wrapped), timeout=timeout)
        stdout = result.stdout
        if "___CWD___\n" in stdout:
            parts = stdout.rsplit("___CWD___\n", 1)
            stdout = parts[0]
            new_cwd = parts[1].strip()
            s["cwd"] = _validate_path(new_cwd)
        return {"stdout": stdout.strip(), "stderr": result.stderr.strip(), "exit_code": result.exit_status, "cwd": s["cwd"]}
    except asyncio.TimeoutError:
        return {"error": f"Command timed out after {timeout}s"}
    except ValueError as e:
        return {"error": str(e)}
    except asyncssh.Error as e:
        return {"error": f"SSH error: {e}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def ssh_session_close(session_id: str) -> dict:
    """Close a persistent SSH session."""
    if session_id not in _sessions:
        return {"error": f"Session '{session_id}' not found."}
    try:
        _sessions[session_id]["conn"].close()
    except Exception as e:
        logger.warning("Error closing session %s: %s", session_id, e)
    del _sessions[session_id]
    return {"status": "closed"}


if __name__ == "__main__":
    mcp.run()
