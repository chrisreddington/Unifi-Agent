# Unifi Agent

Two MCP servers that give Claude full control over UniFi Network infrastructure.

## Architecture

- **unifi-mcp/** — 51 tools wrapping the UniFi Integration API (devices, clients, networks, WiFi, ACLs, firewall zones, vouchers, VPNs, DPI)
- **ssh-mcp/** — 4 tools for SSH command execution on network devices (persistent sessions, working directory tracking, uses ~/.ssh/config)
- **.claude/skills/unifi/** — Claude Code skill with battle-tested payloads and gotchas

## SSH Access to UDM-Pro

- SSH MCP uses system `~/.ssh/config` for host resolution and authentication
- Configure your UDM-Pro as a host alias (e.g. `udm`) in `~/.ssh/config`
- MongoDB at `mongo --port 27117 ace` has full device/site config
- Use this for settings the Integration API doesn't expose (radio config, channel width, etc.)
- After DB changes, queue provisioning: `db.task.insertMany(...)` with `{mac, type:"cmd", cmd:"force-provision"}`
