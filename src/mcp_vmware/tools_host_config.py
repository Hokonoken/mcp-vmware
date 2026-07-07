# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Fine-grained ESXi host configuration tools — equivalent of the esxcli namespaces.

Read (read group): services, network, storage, firewall, advanced settings,
VIBs, health sensors. Write (host.config group): service actions, firewall
ruleset toggles, advanced setting changes, storage rescan.

Everything goes through host.configManager.* (official API), not SSH to the hosts.
"""

from typing import Annotated, Any

from pydantic import Field
from pyVmomi import vim

from .app import tool
from .helpers import (
    ResponseFormat,
    error_text,
    find_host,
    fmt_bytes,
    paginate,
    render_listing,
)
from .roles import deny_message, group_allowed

SERVICE_ACTIONS = ("start", "stop", "restart")
SERVICE_POLICIES = ("on", "off", "automatic")

FORMAT_FIELD = Field(description="markdown (default, compact table) or json (full structure)")


def _gate(group: str) -> str | None:
    return None if group_allowed(group) else deny_message(group)


def _manager(host: vim.HostSystem, name: str) -> Any:
    mgr = getattr(host.configManager, name, None)
    if mgr is None:
        raise RuntimeError(f"{name} unavailable on '{host.name}'.")
    return mgr


# ------------------------------------------------------------------------ read


@tool("vmware_host_services", "Services of a host", group="read", read=True, idempotent=True)
def vmware_host_services(
    host: Annotated[str, Field(description="Name of the ESXi host")],
    response_format: Annotated[ResponseFormat, FORMAT_FIELD] = ResponseFormat.MARKDOWN,
) -> dict[str, Any] | str:
    """Lists the services of an ESXi host (equivalent of esxcli system service list).

    In json: {host, count, services:[{key, label, running, policy, required}]}.
    Act on them with vmware_host_service_action (host.config).
    """
    try:
        h = find_host(host)
        svc_system = _manager(h, "serviceSystem")
        rows = [
            {
                "key": s.key,
                "label": s.label,
                "running": s.running,
                "policy": s.policy,
                "required": s.required,
            }
            for s in svc_system.serviceInfo.service
        ]
        return render_listing(
            f"Services of {h.name}",
            "services",
            rows,
            response_format,
            {"host": h.name, "count": len(rows)},
        )
    except Exception as e:
        return error_text(e)


@tool(
    "vmware_host_network_config",
    "Network config of a host",
    group="read",
    read=True,
    idempotent=True,
)
def vmware_host_network_config(
    host: Annotated[str, Field(description="Name of the ESXi host")],
) -> dict[str, Any] | str:
    """Network configuration of a host (equivalent of esxcli network): vSwitches,
    portgroups, vmkernel interfaces, physical NICs.

    Returns a structured object {host, vswitches:[...], portgroups:[...],
    vmkernel_nics:[...], physical_nics:[...]}.
    """
    try:
        h = find_host(host)
        info = _manager(h, "networkSystem").networkInfo
        return {
            "host": h.name,
            "vswitches": [
                {
                    "name": v.name,
                    "ports": v.numPorts,
                    "mtu": v.mtu,
                    "uplinks": [p.rsplit("-", 1)[-1] for p in (v.pnic or [])],
                }
                for v in (info.vswitch or [])
            ],
            "portgroups": [
                {
                    "name": p.spec.name,
                    "vlan": p.spec.vlanId,
                    "vswitch": p.spec.vswitchName,
                }
                for p in (info.portgroup or [])
            ],
            "vmkernel_nics": [
                {
                    "device": v.device,
                    "ip": v.spec.ip.ipAddress if v.spec.ip else None,
                    "netmask": v.spec.ip.subnetMask if v.spec.ip else None,
                    "mac": v.spec.mac,
                    "mtu": v.spec.mtu,
                    "portgroup": v.portgroup or None,
                }
                for v in (info.vnic or [])
            ],
            "physical_nics": [
                {
                    "device": p.device,
                    "driver": p.driver,
                    "mac": p.mac,
                    "link_speed_mb": p.linkSpeed.speedMb if p.linkSpeed else None,
                    "full_duplex": p.linkSpeed.duplex if p.linkSpeed else None,
                }
                for p in (info.pnic or [])
            ],
        }
    except Exception as e:
        return error_text(e)


@tool("vmware_host_storage", "Storage of a host", group="read", read=True, idempotent=True)
def vmware_host_storage(
    host: Annotated[str, Field(description="Name of the ESXi host")],
    limit: Annotated[int, Field(ge=1, le=500, description="Maximum number of LUNs")] = 50,
    offset: Annotated[int, Field(ge=0, description="Pagination offset for LUNs")] = 0,
    response_format: Annotated[ResponseFormat, FORMAT_FIELD] = ResponseFormat.MARKDOWN,
) -> dict[str, Any] | str:
    """Storage of a host (equivalent of esxcli storage): HBA adapters and paginated LUNs
    with multipath paths.

    In json: {host, adapters:[...], total, count, offset, has_more, next_offset,
    luns:[{canonical_name, model, type, capacity, operational_state, paths}]}.
    Rescan with vmware_host_rescan_storage (host.config).
    """
    try:
        h = find_host(host)
        storage = _manager(h, "storageSystem")
        dev = storage.storageDeviceInfo
        paths_per_lun: dict[str, int] = {}
        if dev.multipathInfo:
            for lun in dev.multipathInfo.lun or []:
                paths_per_lun[lun.lun] = len(lun.path or [])
        all_luns = []
        for lun in dev.scsiLun or []:
            capacity = None
            block_info = getattr(lun, "capacity", None)
            if block_info:
                capacity = fmt_bytes(block_info.block * block_info.blockSize)
            all_luns.append(
                {
                    "canonical_name": lun.canonicalName,
                    "model": f"{lun.vendor.strip()} {lun.model.strip()}"
                    if getattr(lun, "vendor", None)
                    else lun.model,
                    "type": lun.deviceType,
                    "capacity": capacity,
                    "operational_state": list(lun.operationalState or []),
                    "paths": paths_per_lun.get(lun.key),
                }
            )
        page, meta = paginate(all_luns, limit, offset)
        adapters = [
            {
                "device": a.device,
                "model": a.model,
                "driver": a.driver,
                "status": getattr(a, "status", None),
            }
            for a in (dev.hostBusAdapter or [])
        ]
        if response_format == ResponseFormat.JSON:
            return {"host": h.name, "adapters": adapters, **meta, "luns": page}
        from .helpers import md_table

        return "\n".join(
            [
                f"# Storage of {h.name}",
                "",
                f"## Adapters ({len(adapters)})",
                "",
                md_table(adapters),
                "",
                f"## LUNs ({meta['count']} shown of {meta['total']}"
                + (f", more with offset={meta['next_offset']})" if meta["has_more"] else ")"),
                "",
                md_table(page),
            ]
        )
    except Exception as e:
        return error_text(e)


@tool("vmware_host_firewall", "Firewall of a host", group="read", read=True, idempotent=True)
def vmware_host_firewall(
    host: Annotated[str, Field(description="Name of the ESXi host")],
    enabled_only: Annotated[bool, Field(description="Show only enabled rulesets")] = False,
) -> dict[str, Any] | str:
    """Firewall of a host (equivalent of esxcli network firewall): default policy
    and rulesets.

    Returns a structured object {host, default_policy, count, rulesets:[{key, label,
    enabled, all_ips_allowed, allowed_ips}]}. Toggle with vmware_host_firewall_ruleset.
    """
    try:
        h = find_host(host)
        fw = _manager(h, "firewallSystem").firewallInfo
        rulesets = []
        for r in fw.ruleset or []:
            if enabled_only and not r.enabled:
                continue
            rulesets.append(
                {
                    "key": r.key,
                    "label": r.label,
                    "enabled": r.enabled,
                    "all_ips_allowed": r.allowedHosts.allIp if r.allowedHosts else None,
                    "allowed_ips": list(r.allowedHosts.ipAddress or []) if r.allowedHosts else [],
                }
            )
        return {
            "host": h.name,
            "default_policy": {
                "incoming_blocked": fw.defaultPolicy.incomingBlocked,
                "outgoing_blocked": fw.defaultPolicy.outgoingBlocked,
            },
            "count": len(rulesets),
            "rulesets": rulesets,
        }
    except Exception as e:
        return error_text(e)


@tool(
    "vmware_host_advanced_settings",
    "Advanced settings of a host",
    group="read",
    read=True,
    idempotent=True,
)
def vmware_host_advanced_settings(
    host: Annotated[str, Field(description="Name of the ESXi host")],
    filter_prefix: Annotated[
        str,
        Field(
            min_length=2,
            description="Key prefix, e.g. Net., Mem., NFS., UserVars. (required, >1000 settings)",
        ),
    ],
) -> dict[str, Any] | str:
    """Advanced settings of a host (equivalent of esxcli system settings advanced list),
    filtered by key prefix.

    Returns a structured object {host, filter, count, settings:[{key, value}]}.
    Modify with vmware_host_set_advanced_setting (host.config).
    """
    try:
        h = find_host(host)
        adv = _manager(h, "advancedOption")
        try:
            options = adv.QueryOptions(filter_prefix)
        except vim.fault.InvalidName:
            return f"Error: no setting starts with '{filter_prefix}' on '{h.name}'."
        settings = [{"key": o.key, "value": o.value} for o in options]
        return {
            "host": h.name,
            "filter": filter_prefix,
            "count": len(settings),
            "settings": settings,
        }
    except Exception as e:
        return error_text(e)


@tool("vmware_host_vibs", "VIBs installed on a host", group="read", read=True, idempotent=True)
def vmware_host_vibs(
    host: Annotated[str, Field(description="Name of the ESXi host")],
    name_filter: Annotated[
        str | None, Field(description="Substring to search for in the VIB name")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=500, description="Maximum number of results")] = 100,
    offset: Annotated[int, Field(ge=0, description="Pagination offset")] = 0,
    response_format: Annotated[ResponseFormat, FORMAT_FIELD] = ResponseFormat.MARKDOWN,
) -> dict[str, Any] | str:
    """Software packages (VIBs) installed on a host (equivalent of esxcli software vib list)
    and image profile.

    In json: {host, image_profile, total, count, offset, has_more, next_offset,
    vibs:[{name, version, vendor, acceptance_level}]}. In markdown: table.
    """
    try:
        h = find_host(host)
        img = _manager(h, "imageConfigManager")
        packages = img.FetchSoftwarePackages()
        if name_filter:
            packages = [p for p in packages if name_filter.lower() in p.name.lower()]
        packages.sort(key=lambda p: p.name)
        page, meta = paginate(packages, limit, offset)
        try:
            profile = img.HostImageConfigGetProfile().name
        except Exception:
            profile = None
        rows = [
            {
                "name": p.name,
                "version": p.version,
                "vendor": p.vendor,
                "acceptance_level": p.acceptanceLevel,
            }
            for p in page
        ]
        return render_listing(
            f"VIBs of {h.name} (profile: {profile})",
            "vibs",
            rows,
            response_format,
            {"host": h.name, "image_profile": profile, **meta},
        )
    except Exception as e:
        return error_text(e)


@tool("vmware_host_health", "Hardware health of a host", group="read", read=True)
def vmware_host_health(
    host: Annotated[str, Field(description="Name of the ESXi host")],
    all_sensors: Annotated[
        bool, Field(description="List all sensors (default: only abnormal ones)")
    ] = False,
) -> dict[str, Any] | str:
    """Hardware health sensors of a host (equivalent of esxcli hardware): overall
    CPU/memory/storage state and alerting sensors.

    Returns a structured object {host, sensor_count, summary:{green, yellow, red, unknown},
    sensors:[{name, state, reading}]} — by default only non-green sensors are listed.
    """
    try:
        h = find_host(host)
        health = _manager(h, "healthStatusSystem")
        runtime = health.runtime
        sensors = (
            list(runtime.systemHealthInfo.numericSensorInfo or [])
            if runtime.systemHealthInfo
            else []
        )
        summary = {"green": 0, "yellow": 0, "red": 0, "unknown": 0}
        out = []
        for s in sensors:
            state = (s.healthState.key if s.healthState else "unknown").lower()
            summary[state if state in summary else "unknown"] += 1
            if all_sensors or state not in ("green",):
                reading = None
                if s.currentReading is not None and s.unitModifier is not None:
                    reading = f"{s.currentReading * (10**s.unitModifier)} {s.baseUnits or ''}"
                out.append({"name": s.name, "state": state, "reading": reading})
        return {
            "host": h.name,
            "sensor_count": len(sensors),
            "summary": summary,
            "sensors": out,
        }
    except Exception as e:
        return error_text(e)


# ----------------------------------------------------------------- host.config


@tool("vmware_host_service_action", "Act on a host service", group="host.config")
def vmware_host_service_action(
    host: Annotated[str, Field(description="Name of the ESXi host")],
    service_key: Annotated[
        str, Field(description="Service key (see vmware_host_services), e.g. ntpd, TSM-SSH")
    ],
    action: Annotated[
        str | None, Field(description=f"Action: {', '.join(SERVICE_ACTIONS)}")
    ] = None,
    policy: Annotated[
        str | None,
        Field(description=f"Startup policy: {', '.join(SERVICE_POLICIES)}"),
    ] = None,
) -> dict[str, Any] | str:
    """Starts/stops/restarts a host service and/or changes its startup policy
    (equivalent of esxcli system service).

    Provide action and/or policy. Returns an object {action, status, host, service, running}.
    """
    if msg := _gate("host.config"):
        return msg
    if action is None and policy is None:
        return "Error: provide action and/or policy."
    if action is not None and action not in SERVICE_ACTIONS:
        return f"Error: invalid action, choose from: {', '.join(SERVICE_ACTIONS)}."
    if policy is not None and policy not in SERVICE_POLICIES:
        return f"Error: invalid policy, choose from: {', '.join(SERVICE_POLICIES)}."
    try:
        h = find_host(host)
        svc_system = _manager(h, "serviceSystem")
        known = {s.key: s for s in svc_system.serviceInfo.service}
        if service_key not in known:
            return (
                f"Error: service '{service_key}' unknown on '{h.name}'. "
                f"Services: {', '.join(sorted(known))}"
            )
        if policy is not None:
            svc_system.UpdateServicePolicy(id=service_key, policy=policy)
        if action == "start":
            svc_system.StartService(id=service_key)
        elif action == "stop":
            svc_system.StopService(id=service_key)
        elif action == "restart":
            svc_system.RestartService(id=service_key)
        svc_system.RefreshServices()
        running = {s.key: s.running for s in svc_system.serviceInfo.service}.get(service_key)
        return {
            "action": action or "policy_update",
            "status": "success",
            "host": h.name,
            "service": service_key,
            "policy": policy,
            "running": running,
        }
    except Exception as e:
        return error_text(e)


@tool("vmware_host_firewall_ruleset", "Toggle a firewall ruleset", group="host.config")
def vmware_host_firewall_ruleset(
    host: Annotated[str, Field(description="Name of the ESXi host")],
    ruleset_key: Annotated[str, Field(description="Ruleset key (see vmware_host_firewall)")],
    enabled: Annotated[bool, Field(description="true to enable, false to disable")],
) -> dict[str, Any] | str:
    """Enables or disables a ruleset of a host's firewall (equivalent of esxcli network
    firewall ruleset set).

    Returns an object {action, status, host, ruleset, enabled}.
    """
    if msg := _gate("host.config"):
        return msg
    try:
        h = find_host(host)
        fw = _manager(h, "firewallSystem")
        known = [r.key for r in fw.firewallInfo.ruleset or []]
        if ruleset_key not in known:
            return (
                f"Error: ruleset '{ruleset_key}' unknown on '{h.name}' (see vmware_host_firewall)."
            )
        if enabled:
            fw.EnableRuleset(id=ruleset_key)
        else:
            fw.DisableRuleset(id=ruleset_key)
        return {
            "action": "firewall_ruleset",
            "status": "success",
            "host": h.name,
            "ruleset": ruleset_key,
            "enabled": enabled,
        }
    except Exception as e:
        return error_text(e)


@tool("vmware_host_set_advanced_setting", "Modify an advanced setting", group="host.config")
def vmware_host_set_advanced_setting(
    host: Annotated[str, Field(description="Name of the ESXi host")],
    key: Annotated[str, Field(description="Exact setting key, e.g. NFS.MaxVolumes")],
    value: Annotated[str, Field(description="New value (converted to the current type)")],
) -> dict[str, Any] | str:
    """Modifies an advanced setting of a host (equivalent of esxcli system settings advanced
    set). The value is converted to the type of the current value (bool/int/str).

    Returns an object {action, status, host, key, old_value, new_value}.
    """
    if msg := _gate("host.config"):
        return msg
    try:
        h = find_host(host)
        adv = _manager(h, "advancedOption")
        try:
            current = adv.QueryOptions(key)
        except vim.fault.InvalidName:
            return f"Error: setting '{key}' unknown on '{h.name}'."
        exact = [o for o in current if o.key == key]
        if not exact:
            return (
                f"Error: '{key}' is a prefix, not an exact key. Candidates: "
                f"{', '.join(o.key for o in current[:10])}"
            )
        old = exact[0].value
        new_value: Any
        if isinstance(old, bool):
            new_value = value.strip().lower() in ("1", "true", "yes", "on")
        elif isinstance(old, int):
            new_value = int(value)
        else:
            new_value = value
        adv.UpdateOptions(changedValue=[vim.option.OptionValue(key=key, value=new_value)])
        return {
            "action": "set_advanced_setting",
            "status": "success",
            "host": h.name,
            "key": key,
            "old_value": old,
            "new_value": new_value,
        }
    except Exception as e:
        return error_text(e)


@tool("vmware_host_rescan_storage", "Rescan a host's storage", group="host.config")
def vmware_host_rescan_storage(
    host: Annotated[str, Field(description="Name of the ESXi host")],
    rescan_vmfs: Annotated[bool, Field(description="Also look for new VMFS volumes")] = True,
) -> dict[str, Any] | str:
    """Rescans a host's HBAs to detect new LUNs, and optionally new VMFS volumes
    (equivalent of esxcli storage core adapter rescan).

    Risk-free operation but it may take 1 to 2 minutes. Returns an object
    {action, status, host}.
    """
    if msg := _gate("host.config"):
        return msg
    try:
        h = find_host(host)
        storage = _manager(h, "storageSystem")
        storage.RescanAllHba()
        if rescan_vmfs:
            storage.RescanVmfs()
        return {
            "action": "rescan_storage",
            "status": "success",
            "host": h.name,
            "vmfs_rescanned": rescan_vmfs,
        }
    except Exception as e:
        return error_text(e)
