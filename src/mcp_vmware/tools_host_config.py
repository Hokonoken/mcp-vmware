"""Outils de configuration fine des hotes ESXi — equivalent des namespaces esxcli.

Lecture (groupe read) : services, reseau, stockage, firewall, parametres avances,
VIBs, capteurs sante. Ecriture (groupe host.config) : actions sur services, toggle
de rulesets firewall, modification de parametres avances, rescan stockage.

Tout passe par host.configManager.* (API officielle), pas par SSH sur les hotes.
"""

from typing import Annotated, Any

from pydantic import Field
from pyVmomi import vim

from .app import tool
from .helpers import error_text, find_host, fmt_bytes, to_json
from .roles import deny_message, group_allowed

SERVICE_ACTIONS = ("start", "stop", "restart")
SERVICE_POLICIES = ("on", "off", "automatic")


def _gate(group: str) -> str | None:
    return None if group_allowed(group) else deny_message(group)


def _manager(host: vim.HostSystem, name: str) -> Any:
    mgr = getattr(host.configManager, name, None)
    if mgr is None:
        raise RuntimeError(f"{name} indisponible sur '{host.name}'.")
    return mgr


# ------------------------------------------------------------------------ read


@tool("vmware_host_services", "Services d'un hote", group="read", read=True, idempotent=True)
def vmware_host_services(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
) -> str:
    """Liste les services d'un hote ESXi (equivalent esxcli system service list).

    Retourne un JSON {host, count, services:[{key, label, running, policy, required}]}.
    Agir dessus avec vmware_host_service_action (host.config).
    """
    try:
        h = find_host(host)
        svc_system = _manager(h, "serviceSystem")
        services = [
            {
                "key": s.key,
                "label": s.label,
                "running": s.running,
                "policy": s.policy,
                "required": s.required,
            }
            for s in svc_system.serviceInfo.service
        ]
        return to_json({"host": h.name, "count": len(services), "services": services})
    except Exception as e:
        return error_text(e)


@tool(
    "vmware_host_network_config",
    "Config reseau d'un hote",
    group="read",
    read=True,
    idempotent=True,
)
def vmware_host_network_config(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
) -> str:
    """Configuration reseau d'un hote (equivalent esxcli network) : vSwitches,
    portgroups, interfaces vmkernel, NICs physiques.

    Retourne un JSON {host, vswitches:[...], portgroups:[...], vmkernel_nics:[...],
    physical_nics:[...]}.
    """
    try:
        h = find_host(host)
        info = _manager(h, "networkSystem").networkInfo
        return to_json(
            {
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
        )
    except Exception as e:
        return error_text(e)


@tool("vmware_host_storage", "Stockage d'un hote", group="read", read=True, idempotent=True)
def vmware_host_storage(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
) -> str:
    """Stockage d'un hote (equivalent esxcli storage) : adaptateurs HBA, LUNs,
    chemins multipath.

    Retourne un JSON {host, adapters:[...], luns:[{name, model, capacity, paths}]}.
    Rescan avec vmware_host_rescan_storage (host.config).
    """
    try:
        h = find_host(host)
        storage = _manager(h, "storageSystem")
        dev = storage.storageDeviceInfo
        paths_per_lun: dict[str, int] = {}
        if dev.multipathInfo:
            for lun in dev.multipathInfo.lun or []:
                paths_per_lun[lun.lun] = len(lun.path or [])
        luns = []
        for lun in dev.scsiLun or []:
            capacity = None
            block_info = getattr(lun, "capacity", None)
            if block_info:
                capacity = fmt_bytes(block_info.block * block_info.blockSize)
            luns.append(
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
        adapters = [
            {
                "device": a.device,
                "model": a.model,
                "driver": a.driver,
                "status": getattr(a, "status", None),
            }
            for a in (dev.hostBusAdapter or [])
        ]
        return to_json({"host": h.name, "adapters": adapters, "luns": luns})
    except Exception as e:
        return error_text(e)


@tool("vmware_host_firewall", "Firewall d'un hote", group="read", read=True, idempotent=True)
def vmware_host_firewall(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
    enabled_only: Annotated[bool, Field(description="Ne montrer que les rulesets actifs")] = False,
) -> str:
    """Firewall d'un hote (equivalent esxcli network firewall) : politique par defaut
    et rulesets.

    Retourne un JSON {host, default_policy, count, rulesets:[{key, label, enabled,
    all_ips_allowed, allowed_ips}]}. Toggle avec vmware_host_firewall_ruleset.
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
        return to_json(
            {
                "host": h.name,
                "default_policy": {
                    "incoming_blocked": fw.defaultPolicy.incomingBlocked,
                    "outgoing_blocked": fw.defaultPolicy.outgoingBlocked,
                },
                "count": len(rulesets),
                "rulesets": rulesets,
            }
        )
    except Exception as e:
        return error_text(e)


@tool(
    "vmware_host_advanced_settings",
    "Parametres avances d'un hote",
    group="read",
    read=True,
    idempotent=True,
)
def vmware_host_advanced_settings(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
    filter_prefix: Annotated[
        str,
        Field(
            min_length=2,
            description="Prefixe de cle, ex: Net., Mem., NFS., "
            "UserVars. (obligatoire, >1000 parametres)",
        ),
    ],
) -> str:
    """Parametres avances d'un hote (equivalent esxcli system settings advanced list),
    filtres par prefixe de cle.

    Retourne un JSON {host, filter, count, settings:[{key, value}]}. Modifier avec
    vmware_host_set_advanced_setting (host.config).
    """
    try:
        h = find_host(host)
        adv = _manager(h, "advancedOption")
        try:
            options = adv.QueryOptions(filter_prefix)
        except vim.fault.InvalidName:
            return f"Erreur: aucun parametre ne commence par '{filter_prefix}' sur '{h.name}'."
        settings = [{"key": o.key, "value": o.value} for o in options]
        return to_json(
            {"host": h.name, "filter": filter_prefix, "count": len(settings), "settings": settings}
        )
    except Exception as e:
        return error_text(e)


@tool("vmware_host_vibs", "VIBs installes sur un hote", group="read", read=True, idempotent=True)
def vmware_host_vibs(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
    name_filter: Annotated[
        str | None, Field(description="Sous-chaine a chercher dans le nom du VIB")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=500, description="Nombre max de resultats")] = 100,
) -> str:
    """Paquets logiciels (VIBs) installes sur un hote (equivalent esxcli software vib list)
    et profil d'image.

    Retourne un JSON {host, image_profile, total, count, vibs:[{name, version, vendor,
    acceptance_level}]}.
    """
    try:
        h = find_host(host)
        img = _manager(h, "imageConfigManager")
        packages = img.FetchSoftwarePackages()
        if name_filter:
            packages = [p for p in packages if name_filter.lower() in p.name.lower()]
        total = len(packages)
        profile = None
        try:
            profile = img.HostImageConfigGetProfile().name
        except Exception:
            profile = None
        vibs = [
            {
                "name": p.name,
                "version": p.version,
                "vendor": p.vendor,
                "acceptance_level": p.acceptanceLevel,
            }
            for p in packages[:limit]
        ]
        return to_json(
            {
                "host": h.name,
                "image_profile": profile,
                "total": total,
                "count": len(vibs),
                "vibs": vibs,
            }
        )
    except Exception as e:
        return error_text(e)


@tool("vmware_host_health", "Sante materielle d'un hote", group="read", read=True)
def vmware_host_health(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
    all_sensors: Annotated[
        bool, Field(description="Lister tous les capteurs (defaut: seulement les anormaux)")
    ] = False,
) -> str:
    """Capteurs de sante materielle d'un hote (equivalent esxcli hardware) : etat
    global CPU/memoire/stockage et capteurs en alerte.

    Retourne un JSON {host, summary:{green, yellow, red, unknown}, sensors:[{name,
    state, reading}]} — par defaut seuls les capteurs non verts sont listes.
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
        return to_json(
            {
                "host": h.name,
                "sensor_count": len(sensors),
                "summary": summary,
                "sensors": out,
            }
        )
    except Exception as e:
        return error_text(e)


# ----------------------------------------------------------------- host.config


@tool("vmware_host_service_action", "Agir sur un service d'hote", group="host.config")
def vmware_host_service_action(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
    service_key: Annotated[
        str, Field(description="Cle du service (cf. vmware_host_services), ex: ntpd, TSM-SSH")
    ],
    action: Annotated[
        str | None, Field(description=f"Action: {', '.join(SERVICE_ACTIONS)}")
    ] = None,
    policy: Annotated[
        str | None,
        Field(description=f"Politique de demarrage: {', '.join(SERVICE_POLICIES)}"),
    ] = None,
) -> str:
    """Demarre/arrete/redemarre un service d'hote et/ou change sa politique de demarrage
    (equivalent esxcli system service).

    Fournir action et/ou policy. Retourne un JSON {action, status, host, service, running}.
    """
    if msg := _gate("host.config"):
        return msg
    if action is None and policy is None:
        return "Erreur: fournir action et/ou policy."
    if action is not None and action not in SERVICE_ACTIONS:
        return f"Erreur: action invalide, choisir parmi: {', '.join(SERVICE_ACTIONS)}."
    if policy is not None and policy not in SERVICE_POLICIES:
        return f"Erreur: policy invalide, choisir parmi: {', '.join(SERVICE_POLICIES)}."
    try:
        h = find_host(host)
        svc_system = _manager(h, "serviceSystem")
        known = {s.key: s for s in svc_system.serviceInfo.service}
        if service_key not in known:
            return (
                f"Erreur: service '{service_key}' inconnu sur '{h.name}'. "
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
        return to_json(
            {
                "action": action or "policy_update",
                "status": "success",
                "host": h.name,
                "service": service_key,
                "policy": policy,
                "running": running,
            }
        )
    except Exception as e:
        return error_text(e)


@tool("vmware_host_firewall_ruleset", "Toggle d'un ruleset firewall", group="host.config")
def vmware_host_firewall_ruleset(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
    ruleset_key: Annotated[str, Field(description="Cle du ruleset (cf. vmware_host_firewall)")],
    enabled: Annotated[bool, Field(description="true pour activer, false pour desactiver")],
) -> str:
    """Active ou desactive un ruleset du firewall d'un hote (equivalent esxcli network
    firewall ruleset set).

    Retourne un JSON {action, status, host, ruleset, enabled}.
    """
    if msg := _gate("host.config"):
        return msg
    try:
        h = find_host(host)
        fw = _manager(h, "firewallSystem")
        known = [r.key for r in fw.firewallInfo.ruleset or []]
        if ruleset_key not in known:
            return (
                f"Erreur: ruleset '{ruleset_key}' inconnu sur '{h.name}' "
                "(cf. vmware_host_firewall)."
            )
        if enabled:
            fw.EnableRuleset(id=ruleset_key)
        else:
            fw.DisableRuleset(id=ruleset_key)
        return to_json(
            {
                "action": "firewall_ruleset",
                "status": "success",
                "host": h.name,
                "ruleset": ruleset_key,
                "enabled": enabled,
            }
        )
    except Exception as e:
        return error_text(e)


@tool("vmware_host_set_advanced_setting", "Modifier un parametre avance", group="host.config")
def vmware_host_set_advanced_setting(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
    key: Annotated[str, Field(description="Cle exacte du parametre, ex: NFS.MaxVolumes")],
    value: Annotated[str, Field(description="Nouvelle valeur (convertie au type actuel)")],
) -> str:
    """Modifie un parametre avance d'un hote (equivalent esxcli system settings advanced
    set). La valeur est convertie au type de la valeur actuelle (bool/int/str).

    Retourne un JSON {action, status, host, key, old_value, new_value}.
    """
    if msg := _gate("host.config"):
        return msg
    try:
        h = find_host(host)
        adv = _manager(h, "advancedOption")
        try:
            current = adv.QueryOptions(key)
        except vim.fault.InvalidName:
            return f"Erreur: parametre '{key}' inconnu sur '{h.name}'."
        exact = [o for o in current if o.key == key]
        if not exact:
            return (
                f"Erreur: '{key}' est un prefixe, pas une cle exacte. Candidats: "
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
        return to_json(
            {
                "action": "set_advanced_setting",
                "status": "success",
                "host": h.name,
                "key": key,
                "old_value": old,
                "new_value": new_value,
            }
        )
    except Exception as e:
        return error_text(e)


@tool("vmware_host_rescan_storage", "Rescan du stockage d'un hote", group="host.config")
def vmware_host_rescan_storage(
    host: Annotated[str, Field(description="Nom de l'hote ESXi")],
    rescan_vmfs: Annotated[
        bool, Field(description="Chercher aussi de nouveaux volumes VMFS")
    ] = True,
) -> str:
    """Rescan des HBA d'un hote pour detecter de nouvelles LUNs, et optionnellement de
    nouveaux volumes VMFS (equivalent esxcli storage core adapter rescan).

    Operation sans risque mais qui peut durer 1 a 2 minutes. Retourne un JSON
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
        return to_json(
            {
                "action": "rescan_storage",
                "status": "success",
                "host": h.name,
                "vmfs_rescanned": rescan_vmfs,
            }
        )
    except Exception as e:
        return error_text(e)
