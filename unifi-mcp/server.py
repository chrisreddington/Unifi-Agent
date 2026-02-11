"""UniFi Network MCP Server — exposes UniFi Network API v10.0.162 as MCP tools."""

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

mcp = FastMCP("unifi_mcp")

UNIFI_HOST = os.environ.get("UNIFI_HOST", "")
UNIFI_API_KEY = os.environ.get("UNIFI_API_KEY", "")
UNIFI_SITE_ID = os.environ.get("UNIFI_SITE_ID", "")


def _site(site_id: str | None = None) -> str:
    sid = site_id or UNIFI_SITE_ID
    if not sid:
        raise ValueError("site_id required — pass it or set UNIFI_SITE_ID env var")
    return sid


def _handle_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        r = e.response
        try:
            body = r.json()
        except Exception:
            body = r.text
        messages = {401: "Unauthorized — check UNIFI_API_KEY", 403: "Forbidden — API key lacks permission", 404: "Not found — check resource ID", 429: "Rate limited — wait and retry"}
        hint = messages.get(r.status_code, f"HTTP {r.status_code}")
        return f"{hint}: {body}"
    if isinstance(e, httpx.TimeoutException):
        return f"Timeout connecting to {UNIFI_HOST}"
    return str(e)


async def _api(method: str, path: str, params: dict | None = None, body: Any = None) -> Any:
    if not UNIFI_HOST or not UNIFI_API_KEY:
        raise ValueError("Set UNIFI_HOST and UNIFI_API_KEY environment variables")
    url = f"{UNIFI_HOST.rstrip('/')}/proxy/network/integration{path}"
    headers = {"X-API-KEY": UNIFI_API_KEY, "Content-Type": "application/json"}
    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        try:
            r = await client.request(method, url, headers=headers, params=params, json=body)
            r.raise_for_status()
            return r.json() if r.content else {"status": "ok"}
        except Exception as e:
            return {"error": _handle_error(e)}


# ── Pydantic Input Models ──


class NetworkConfig(BaseModel):
    """Network creation/update config. Shape varies by management type (GATEWAY, SWITCH, UNMANAGED).
    Fields: name (str), management (str), enabled (bool), vlanId (int 2-4000),
    ipv4Configuration (dict with subnet, gatewayIp), dhcpConfiguration (dict with mode, dns, range)."""
    model_config = ConfigDict(extra="allow")
    name: str
    management: str = Field(description="GATEWAY | SWITCH | UNMANAGED")
    enabled: bool = True
    vlanId: int | None = Field(None, ge=2, le=4000)
    ipv4Configuration: dict | None = None
    dhcpConfiguration: dict | None = None


class WifiConfig(BaseModel):
    """WiFi broadcast config. Fields: name, type (STANDARD|IOT_OPTIMIZED), enabled, band (2.4GHz|5GHz|both),
    securityConfiguration (dict with protocol, passphrase), networkId (str)."""
    model_config = ConfigDict(extra="allow")
    name: str
    type: str = Field("STANDARD", description="STANDARD | IOT_OPTIMIZED")
    enabled: bool = True
    band: str | None = None
    securityConfiguration: dict | None = None
    networkId: str | None = None


class AclRuleConfig(BaseModel):
    """ACL rule config. Fields: name, type (IPV4|MAC), action (ALLOW|BLOCK), enabled, index (int),
    sourceFilter (dict with type + networkIds or ipAddressesOrSubnets), destinationFilter (same), protocolFilter (list)."""
    model_config = ConfigDict(extra="allow")
    name: str
    type: str = Field(description="IPV4 | MAC")
    action: str = Field(description="ALLOW | BLOCK")
    enabled: bool = True
    index: int | None = None
    sourceFilter: dict | None = None
    destinationFilter: dict | None = None
    protocolFilter: list[str] | None = None


class TrafficMatchingListConfig(BaseModel):
    """Traffic matching list config. Fields: name, type (PORTS|IPV4_ADDRESSES|IPV6_ADDRESSES), items (list of dicts)."""
    model_config = ConfigDict(extra="allow")
    name: str
    type: str = Field(description="PORTS | IPV4_ADDRESSES | IPV6_ADDRESSES")
    items: list[dict] = Field(default_factory=list)


class VoucherCreateInput(BaseModel):
    """Voucher creation input. Fields: name, timeLimitMinutes (1-1000000), count (1-1000),
    optional authorizedGuestLimit, dataUsageLimitMBytes, rxRateLimitKbps, txRateLimitKbps."""
    model_config = ConfigDict(extra="allow")
    name: str
    timeLimitMinutes: int = Field(ge=1, le=1000000)
    count: int = Field(1, ge=1, le=1000)
    dataUsageLimitMBytes: int | None = None
    rxRateLimitKbps: int | None = None
    txRateLimitKbps: int | None = None


class FirewallZoneInput(BaseModel):
    """Firewall zone config. Fields: name (str), networkIds (list of network ID strings)."""
    model_config = ConfigDict(extra="allow")
    name: str
    networkIds: list[str] = Field(default_factory=list)


# ── Tools: Info & Sites ──


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_get_app_info() -> Any:
    """Get UniFi Network application info (version, hostname, etc.)."""
    return await _api("GET", "/v1/info")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_sites() -> Any:
    """List all sites managed by this UniFi controller."""
    return await _api("GET", "/v1/sites")


# ── Tools: Devices ──


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_devices(site_id: str | None = None) -> Any:
    """List all adopted devices at a site. Returns name, model, mac, state, firmware info."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/devices")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_get_device(device_id: str, site_id: str | None = None) -> Any:
    """Get detailed info for a single device by its ID."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/devices/{device_id}")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_get_device_stats(device_id: str, site_id: str | None = None) -> Any:
    """Get latest statistics for a device (uptime, throughput, CPU, memory)."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/devices/{device_id}/statistics/latest")


@mcp.tool(annotations={"destructiveHint": True})
async def unifi_restart_device(device_id: str, site_id: str | None = None) -> Any:
    """Restart (reboot) a device. Action: RESTART."""
    return await _api("POST", f"/v1/sites/{_site(site_id)}/devices/{device_id}/actions", body={"action": "RESTART"})


@mcp.tool(annotations={"destructiveHint": True})
async def unifi_power_cycle_port(device_id: str, port_idx: int, site_id: str | None = None) -> Any:
    """Power-cycle a specific PoE port on a switch. Action: POWER_CYCLE."""
    return await _api("POST", f"/v1/sites/{_site(site_id)}/devices/{device_id}/interfaces/ports/{port_idx}/actions", body={"action": "POWER_CYCLE"})


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_pending_devices() -> Any:
    """List devices pending adoption (not yet site-scoped)."""
    return await _api("GET", "/v1/pending-devices")


# ── Tools: Clients ──


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_clients(site_id: str | None = None) -> Any:
    """List all connected clients at a site. Returns name, mac, ip, type, network."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/clients")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_get_client(client_id: str, site_id: str | None = None) -> Any:
    """Get detailed info for a single client by its ID."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/clients/{client_id}")


@mcp.tool(annotations={"destructiveHint": False, "openWorldHint": True})
async def unifi_authorize_guest(client_id: str, site_id: str | None = None) -> Any:
    """Authorize a guest client (e.g. after captive portal). Action: AUTHORIZE_GUEST."""
    return await _api("POST", f"/v1/sites/{_site(site_id)}/clients/{client_id}/actions", body={"action": "AUTHORIZE_GUEST"})


@mcp.tool(annotations={"destructiveHint": True})
async def unifi_unauthorize_guest(client_id: str, site_id: str | None = None) -> Any:
    """Revoke guest authorization for a client. Action: UNAUTHORIZE_GUEST."""
    return await _api("POST", f"/v1/sites/{_site(site_id)}/clients/{client_id}/actions", body={"action": "UNAUTHORIZE_GUEST"})


# ── Tools: Networks ──


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_networks(site_id: str | None = None) -> Any:
    """List all networks at a site. Returns name, management type, vlanId, subnet."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/networks")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_get_network(network_id: str, site_id: str | None = None) -> Any:
    """Get detailed info for a single network by its ID."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/networks/{network_id}")


@mcp.tool(annotations={"destructiveHint": False})
async def unifi_create_network(config: NetworkConfig, site_id: str | None = None) -> Any:
    """Create a new network. Provide a NetworkConfig with name, management (GATEWAY|SWITCH|UNMANAGED),
    optional vlanId (2-4000), ipv4Configuration (subnet, gatewayIp), dhcpConfiguration (mode, dns, range)."""
    return await _api("POST", f"/v1/sites/{_site(site_id)}/networks", body=config.model_dump(exclude_none=True))


@mcp.tool(annotations={"idempotentHint": True})
async def unifi_update_network(network_id: str, config: NetworkConfig, site_id: str | None = None) -> Any:
    """Update an existing network by ID. Provide full NetworkConfig (PUT semantics — all fields required)."""
    return await _api("PUT", f"/v1/sites/{_site(site_id)}/networks/{network_id}", body=config.model_dump(exclude_none=True))


@mcp.tool(annotations={"destructiveHint": True})
async def unifi_delete_network(network_id: str, site_id: str | None = None) -> Any:
    """Delete a network by ID. Check references first with unifi_get_network_references."""
    return await _api("DELETE", f"/v1/sites/{_site(site_id)}/networks/{network_id}")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_get_network_references(network_id: str, site_id: str | None = None) -> Any:
    """Get resources referencing this network (WiFi, firewall zones, etc.). Check before deleting."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/networks/{network_id}/references")


# ── Tools: WiFi Broadcasts ──


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_wifi(site_id: str | None = None) -> Any:
    """List all WiFi broadcasts (SSIDs) at a site."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/wifi/broadcasts")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_get_wifi(wifi_id: str, site_id: str | None = None) -> Any:
    """Get detailed info for a single WiFi broadcast by its ID."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/wifi/broadcasts/{wifi_id}")


@mcp.tool(annotations={"destructiveHint": False})
async def unifi_create_wifi(config: WifiConfig, site_id: str | None = None) -> Any:
    """Create a new WiFi broadcast. Provide WifiConfig with name, type (STANDARD|IOT_OPTIMIZED),
    securityConfiguration (protocol, passphrase), networkId, band."""
    return await _api("POST", f"/v1/sites/{_site(site_id)}/wifi/broadcasts", body=config.model_dump(exclude_none=True))


@mcp.tool(annotations={"idempotentHint": True})
async def unifi_update_wifi(wifi_id: str, config: WifiConfig, site_id: str | None = None) -> Any:
    """Update an existing WiFi broadcast by ID. Provide full WifiConfig (PUT semantics)."""
    return await _api("PUT", f"/v1/sites/{_site(site_id)}/wifi/broadcasts/{wifi_id}", body=config.model_dump(exclude_none=True))


@mcp.tool(annotations={"destructiveHint": True})
async def unifi_delete_wifi(wifi_id: str, site_id: str | None = None) -> Any:
    """Delete a WiFi broadcast by ID."""
    return await _api("DELETE", f"/v1/sites/{_site(site_id)}/wifi/broadcasts/{wifi_id}")


# ── Tools: Hotspot Vouchers ──


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_vouchers(site_id: str | None = None) -> Any:
    """List all hotspot vouchers at a site."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/hotspot/vouchers")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_get_voucher(voucher_id: str, site_id: str | None = None) -> Any:
    """Get detailed info for a single voucher by its ID."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/hotspot/vouchers/{voucher_id}")


@mcp.tool(annotations={"destructiveHint": False})
async def unifi_create_vouchers(config: VoucherCreateInput, site_id: str | None = None) -> Any:
    """Create hotspot vouchers. Provide VoucherCreateInput with name, timeLimitMinutes (1-1000000),
    count (1-1000), optional authorizedGuestLimit, dataUsageLimitMBytes, rxRateLimitKbps, txRateLimitKbps."""
    return await _api("POST", f"/v1/sites/{_site(site_id)}/hotspot/vouchers", body=config.model_dump(exclude_none=True))


@mcp.tool(annotations={"destructiveHint": True})
async def unifi_delete_voucher(voucher_id: str, site_id: str | None = None) -> Any:
    """Delete a single voucher by ID."""
    return await _api("DELETE", f"/v1/sites/{_site(site_id)}/hotspot/vouchers/{voucher_id}")


@mcp.tool(annotations={"destructiveHint": True})
async def unifi_bulk_delete_vouchers(voucher_filter: str, site_id: str | None = None) -> Any:
    """Bulk-delete vouchers matching a filter string (e.g. 'expired', 'unused')."""
    return await _api("DELETE", f"/v1/sites/{_site(site_id)}/hotspot/vouchers", params={"filter": voucher_filter})


# ── Tools: Firewall Zones ──


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_firewall_zones(site_id: str | None = None) -> Any:
    """List all firewall zones at a site."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/firewall/zones")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_get_firewall_zone(zone_id: str, site_id: str | None = None) -> Any:
    """Get detailed info for a single firewall zone by its ID."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/firewall/zones/{zone_id}")


@mcp.tool(annotations={"destructiveHint": False})
async def unifi_create_firewall_zone(config: FirewallZoneInput, site_id: str | None = None) -> Any:
    """Create a new firewall zone. Provide FirewallZoneInput with name and networkIds list."""
    return await _api("POST", f"/v1/sites/{_site(site_id)}/firewall/zones", body=config.model_dump(exclude_none=True))


@mcp.tool(annotations={"idempotentHint": True})
async def unifi_update_firewall_zone(zone_id: str, config: FirewallZoneInput, site_id: str | None = None) -> Any:
    """Update an existing firewall zone by ID. Provide full FirewallZoneInput (PUT semantics)."""
    return await _api("PUT", f"/v1/sites/{_site(site_id)}/firewall/zones/{zone_id}", body=config.model_dump(exclude_none=True))


@mcp.tool(annotations={"destructiveHint": True})
async def unifi_delete_firewall_zone(zone_id: str, site_id: str | None = None) -> Any:
    """Delete a firewall zone by ID."""
    return await _api("DELETE", f"/v1/sites/{_site(site_id)}/firewall/zones/{zone_id}")


# ── Tools: ACL Rules ──


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_acl_rules(site_id: str | None = None) -> Any:
    """List all ACL rules at a site."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/acl-rules")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_get_acl_rule(rule_id: str, site_id: str | None = None) -> Any:
    """Get detailed info for a single ACL rule by its ID."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/acl-rules/{rule_id}")


@mcp.tool(annotations={"destructiveHint": False})
async def unifi_create_acl_rule(config: AclRuleConfig, site_id: str | None = None) -> Any:
    """Create a new ACL rule. Provide AclRuleConfig with name, type (IPV4|MAC), action (ALLOW|BLOCK),
    enabled, index, sourceFilter, destinationFilter, protocolFilter."""
    return await _api("POST", f"/v1/sites/{_site(site_id)}/acl-rules", body=config.model_dump(exclude_none=True))


@mcp.tool(annotations={"idempotentHint": True})
async def unifi_update_acl_rule(rule_id: str, config: AclRuleConfig, site_id: str | None = None) -> Any:
    """Update an existing ACL rule by ID. Provide full AclRuleConfig (PUT semantics)."""
    return await _api("PUT", f"/v1/sites/{_site(site_id)}/acl-rules/{rule_id}", body=config.model_dump(exclude_none=True))


@mcp.tool(annotations={"destructiveHint": True})
async def unifi_delete_acl_rule(rule_id: str, site_id: str | None = None) -> Any:
    """Delete an ACL rule by ID."""
    return await _api("DELETE", f"/v1/sites/{_site(site_id)}/acl-rules/{rule_id}")


# ── Tools: Traffic Matching Lists ──


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_traffic_matching_lists(site_id: str | None = None) -> Any:
    """List all traffic matching lists at a site."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/traffic-matching-lists")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_get_traffic_matching_list(list_id: str, site_id: str | None = None) -> Any:
    """Get detailed info for a single traffic matching list by its ID."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/traffic-matching-lists/{list_id}")


@mcp.tool(annotations={"destructiveHint": False})
async def unifi_create_traffic_matching_list(config: TrafficMatchingListConfig, site_id: str | None = None) -> Any:
    """Create a new traffic matching list. Provide TrafficMatchingListConfig with name,
    type (PORTS|IPV4_ADDRESSES|IPV6_ADDRESSES), items (list of dicts)."""
    return await _api("POST", f"/v1/sites/{_site(site_id)}/traffic-matching-lists", body=config.model_dump(exclude_none=True))


@mcp.tool(annotations={"idempotentHint": True})
async def unifi_update_traffic_matching_list(list_id: str, config: TrafficMatchingListConfig, site_id: str | None = None) -> Any:
    """Update an existing traffic matching list by ID. Provide full TrafficMatchingListConfig (PUT semantics)."""
    return await _api("PUT", f"/v1/sites/{_site(site_id)}/traffic-matching-lists/{list_id}", body=config.model_dump(exclude_none=True))


@mcp.tool(annotations={"destructiveHint": True})
async def unifi_delete_traffic_matching_list(list_id: str, site_id: str | None = None) -> Any:
    """Delete a traffic matching list by ID."""
    return await _api("DELETE", f"/v1/sites/{_site(site_id)}/traffic-matching-lists/{list_id}")


# ── Tools: Supporting Resources (Read-Only) ──


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_wans(site_id: str | None = None) -> Any:
    """List all WAN interfaces at a site."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/wans")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_vpn_tunnels(site_id: str | None = None) -> Any:
    """List all site-to-site VPN tunnels at a site."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/vpn/site-to-site-tunnels")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_vpn_servers(site_id: str | None = None) -> Any:
    """List all VPN servers at a site."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/vpn/servers")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_radius_profiles(site_id: str | None = None) -> Any:
    """List all RADIUS profiles at a site."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/radius/profiles")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_device_tags(site_id: str | None = None) -> Any:
    """List all device tags at a site."""
    return await _api("GET", f"/v1/sites/{_site(site_id)}/device-tags")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_dpi_categories() -> Any:
    """List all DPI (Deep Packet Inspection) categories. Not site-scoped."""
    return await _api("GET", "/v1/dpi/categories")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_dpi_applications() -> Any:
    """List all DPI applications. Not site-scoped."""
    return await _api("GET", "/v1/dpi/applications")


@mcp.tool(annotations={"readOnlyHint": True})
async def unifi_list_countries() -> Any:
    """List all countries (used for regulatory/channel config). Not site-scoped."""
    return await _api("GET", "/v1/countries")


if __name__ == "__main__":
    mcp.run()
