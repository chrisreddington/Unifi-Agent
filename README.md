# Unifi Agent

AI-powered UniFi network management through [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Two MCP servers expose 55 tools that let Claude manage your entire UniFi infrastructure — devices, clients, networks, WiFi, firewall rules, VLANs, hotspot vouchers, and more. An SSH server provides direct shell access for advanced configuration beyond the API.

## What Can It Do?

Ask Claude things like:
- "List all devices and show me which ones have high CPU usage"
- "Create a guest network on VLAN 50 with a captive portal"
- "Set up an ACL rule to block IoT devices from reaching the management VLAN"
- "Generate 20 hotspot vouchers for tomorrow's event, 24hr limit, 10Mbps cap"
- "Change all AP channel widths to 160MHz" *(via SSH + MongoDB)*
- "Show me all clients connected to the EFB network"

## Architecture

```
unifi-mcp/          51 tools — UniFi Integration API (Python, httpx, Pydantic)
ssh-mcp/             4 tools — SSH command execution (Python, asyncssh, uses ~/.ssh/config)
.claude/skills/      Claude Code skill with example payloads and gotchas
```

## Prerequisites

- [Python 3.11+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- UniFi Network controller with [Integration API](https://help.ui.com/hc/en-us/articles/32910498498583-UniFi-Integration-API) enabled
- API key from **UniFi Network > Settings > API**

## Quick Start

**1. Clone and install dependencies:**
```bash
git clone https://github.com/brianbell-x/Unifi-Agent.git
cd Unifi-Agent
cd unifi-mcp && uv sync && cd ..
cd ssh-mcp && uv sync && cd ..
```

**2. Configure credentials:**
```bash
cp .mcp.json.sample .mcp.json
```

Edit `.mcp.json` with your controller URL, API key, and site ID:
```json
{
  "mcpServers": {
    "unifi": {
      "env": {
        "UNIFI_HOST": "https://192.168.1.1",
        "UNIFI_API_KEY": "your-api-key-here",
        "UNIFI_SITE_ID": "your-site-id"
      }
    }
  }
}
```

**3. Configure SSH access (uses system SSH config):**

Add your UDM-Pro to `~/.ssh/config`:
```
Host udm
    HostName 192.168.1.1
    User root
    IdentityFile ~/.ssh/id_ed25519
```

Ensure the host key is in your known_hosts:
```bash
ssh-keyscan 192.168.1.1 >> ~/.ssh/known_hosts
```

**4. Find your Site ID:**
```bash
# Start Claude Code from the project directory
claude
# Then ask: "List all sites"
```

**4. Start using it:**
```bash
claude
```

Claude will automatically connect to both MCP servers and have access to all 56 tools.

## Tools

### UniFi MCP (51 tools)

| Category | Tools | Operations |
|----------|-------|------------|
| **Info & Sites** | `get_app_info`, `list_sites` | Controller version, managed sites |
| **Devices** | `list_devices`, `get_device`, `get_device_stats`, `restart_device`, `power_cycle_port`, `list_pending_devices` | Monitor, reboot, PoE cycle |
| **Clients** | `list_clients`, `get_client`, `authorize_guest`, `unauthorize_guest` | Connected clients, guest portal |
| **Networks** | `list_networks`, `get_network`, `create_network`, `update_network`, `delete_network`, `get_network_references` | VLAN/subnet CRUD |
| **WiFi** | `list_wifi`, `get_wifi`, `create_wifi`, `update_wifi`, `delete_wifi` | SSID CRUD |
| **Vouchers** | `list_vouchers`, `get_voucher`, `create_vouchers`, `delete_voucher`, `bulk_delete_vouchers` | Hotspot passes |
| **Firewall** | `list_firewall_zones`, `get_firewall_zone`, `create_firewall_zone`, `update_firewall_zone`, `delete_firewall_zone` | Zone management |
| **ACL Rules** | `list_acl_rules`, `get_acl_rule`, `create_acl_rule`, `update_acl_rule`, `delete_acl_rule` | Traffic filtering |
| **Traffic Lists** | `list_traffic_matching_lists`, `get_traffic_matching_list`, `create_traffic_matching_list`, `update_traffic_matching_list`, `delete_traffic_matching_list` | Port/IP groups |
| **Supporting** | `list_wans`, `list_vpn_tunnels`, `list_vpn_servers`, `list_radius_profiles`, `list_device_tags`, `list_dpi_categories`, `list_dpi_applications`, `list_countries` | Read-only |

### SSH MCP (4 tools)

| Tool | Description |
|------|-------------|
| `ssh_execute` | One-shot command on a remote host |
| `ssh_session_start` | Open persistent session (30min timeout) |
| `ssh_session_command` | Run command in session (preserves cwd) |
| `ssh_session_close` | Close a session |

## Advanced: Direct Device Access

The Integration API doesn't expose everything. For radio configuration, channel widths, min-RSSI thresholds, and other low-level settings, the SSH MCP server connects directly to the UDM-Pro's MongoDB:

```bash
# Example: Change 5GHz channel width to 160MHz on all APs
mongo --port 27117 ace --eval '
  db.device.updateMany(
    {"model": "U7P"},
    {$set: {"radio_table.$[r].ht": "160"}},
    {arrayFilters: [{"r.radio": "na"}]}
  )
'
# Then force-provision to apply
db.task.insertMany(
  db.device.find({"model":"U7P"}, {mac:1, _id:0}).toArray().map(d => ({
    mac: d.mac, type: "cmd", cmd: "force-provision", _id: new ObjectId()
  }))
)
```

## Key Gotchas

- **Pagination**: List endpoints return max 25 items (vouchers: 100). No offset/limit params — first page only.
- **WiFi/Network creation**: The API requires many more fields than the schema suggests. The skill file (`.claude/skills/unifi/SKILL.md`) has complete working payloads.
- **ACL rule ordering**: Lower `index` = higher priority (first-match-wins).
- **Bulk delete filter syntax**: Values with spaces need single quotes: `name.eq('My Thing')`.
- **SSL verification**: Enabled by default (uses system CA store). For self-signed certs, set `UNIFI_CA_BUNDLE=/path/to/cert.pem` in `.mcp.json` env, or set `UNIFI_SSL_VERIFY=false` to disable (not recommended).
- **SSH access**: Uses your system `~/.ssh/config` and `~/.ssh/known_hosts`. No separate credentials file needed.

## License

[MIT](LICENSE)
