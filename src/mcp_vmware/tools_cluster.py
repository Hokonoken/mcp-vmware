# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Cluster tools: fine-grained HA/DRS reads (read group) and control (cluster.ops group)."""

from typing import Annotated, Any

from pydantic import Field
from pyVmomi import vim

from .app import tool
from .helpers import error_text, find_cluster, find_vm, wait_for_task
from .roles import deny_message, group_allowed

DRS_BEHAVIORS = ("manual", "partiallyAutomated", "fullyAutomated")


def _gate(group: str) -> str | None:
    return None if group_allowed(group) else deny_message(group)


def _rule_summary(rule: Any) -> dict[str, Any]:
    kind = "unknown"
    if isinstance(rule, vim.cluster.AffinityRuleSpec):
        kind = "affinity"
    elif isinstance(rule, vim.cluster.AntiAffinityRuleSpec):
        kind = "anti_affinity"
    elif isinstance(rule, vim.cluster.VmHostRuleInfo):
        kind = "vm_host"
    return {
        "key": rule.key,
        "name": rule.name,
        "type": kind,
        "enabled": rule.enabled,
        "vms": [v.name for v in getattr(rule, "vm", []) or []],
    }


@tool(
    "vmware_get_cluster_config",
    "HA/DRS config of a cluster",
    group="read",
    read=True,
    idempotent=True,
)
def vmware_get_cluster_config(
    cluster: Annotated[str, Field(description="Cluster name (see vmware_list_clusters)")],
) -> dict[str, Any] | str:
    """Detailed HA (DAS) and DRS configuration of a cluster + failover capacity.

    Returns a JSON {name, ha:{enabled, admission_control_enabled, failover_level,
    restart_priority, current_failover_level}, drs:{enabled, behavior, vmotion_rate},
    rules_count}.
    """
    try:
        c = find_cluster(cluster)
        cfg = c.configurationEx
        das, drs = cfg.dasConfig, cfg.drsConfig
        runtime = None
        try:
            info = c.RetrieveDasAdvancedRuntimeInfo()
            if info is not None:
                runtime = getattr(info, "dasHostInfo", None)
        except Exception:
            runtime = None
        ha = {
            "enabled": das.enabled if das else None,
            "admission_control_enabled": das.admissionControlEnabled if das else None,
            "restart_priority": das.defaultVmSettings.restartPriority
            if das and das.defaultVmSettings
            else None,
            "host_monitoring": das.hostMonitoring if das else None,
            "vm_monitoring": das.vmMonitoring if das else None,
        }
        policy = das.admissionControlPolicy if das else None
        if isinstance(policy, vim.cluster.FailoverLevelAdmissionControlPolicy):
            ha["failover_level"] = policy.failoverLevel
        return {
            "name": c.name,
            "moid": c._moId,
            "ha": ha,
            "drs": {
                "enabled": drs.enabled if drs else None,
                "behavior": str(drs.defaultVmBehavior) if drs else None,
                "vmotion_rate": drs.vmotionRate if drs else None,
            },
            "rules_count": len(cfg.rule or []),
            "das_runtime_present": runtime is not None,
        }
    except Exception as e:
        return error_text(e)


@tool("vmware_drs_recommendations", "DRS recommendations", group="read", read=True)
def vmware_drs_recommendations(
    cluster: Annotated[str, Field(description="Cluster name")],
    refresh: Annotated[bool, Field(description="Force a recomputation before reading")] = False,
) -> dict[str, Any] | str:
    """Lists the pending DRS recommendations of a cluster (proposed migrations).

    Returns a JSON {cluster, count, recommendations:[{key, type, reason, target,
    actions:[...]}]}. Apply afterwards with vmware_apply_drs_recommendation (cluster.ops).
    """
    try:
        c = find_cluster(cluster)
        if refresh:
            c.RefreshRecommendation()
        recs = []
        for r in c.recommendation or []:
            actions = []
            for a in r.action or []:
                if isinstance(a, vim.cluster.MigrationAction) and a.drsMigration:
                    actions.append(
                        f"migrate {a.drsMigration.vm.name} -> {a.drsMigration.destination.name}"
                    )
                else:
                    actions.append(type(a).__name__)
            recs.append(
                {
                    "key": r.key,
                    "type": r.type,
                    "reason": r.reasonText,
                    "target": r.target.name if r.target else None,
                    "rating": r.rating,
                    "actions": actions,
                }
            )
        return {"cluster": c.name, "count": len(recs), "recommendations": recs}
    except Exception as e:
        return error_text(e)


@tool("vmware_list_affinity_rules", "Affinity rules", group="read", read=True, idempotent=True)
def vmware_list_affinity_rules(
    cluster: Annotated[str, Field(description="Cluster name")],
) -> dict[str, Any] | str:
    """Lists the affinity / anti-affinity / VM-host rules of a cluster.

    Returns a JSON {cluster, count, rules:[{key, name, type, enabled, vms}]}.
    """
    try:
        c = find_cluster(cluster)
        rules = [_rule_summary(r) for r in (c.configurationEx.rule or [])]
        return {"cluster": c.name, "count": len(rules), "rules": rules}
    except Exception as e:
        return error_text(e)


@tool("vmware_set_drs", "Configure DRS", group="cluster.ops")
def vmware_set_drs(
    cluster: Annotated[str, Field(description="Cluster name")],
    enabled: Annotated[bool | None, Field(description="Enable/disable DRS")] = None,
    behavior: Annotated[
        str | None,
        Field(description=f"DRS mode: {', '.join(DRS_BEHAVIORS)}"),
    ] = None,
    vmotion_rate: Annotated[
        int | None,
        Field(ge=1, le=5, description="Migration aggressiveness (1=conservative, 5=aggressive)"),
    ] = None,
) -> dict[str, Any] | str:
    """Modifies the DRS configuration of a cluster (enablement, mode, aggressiveness).

    Provide at least one parameter. Returns a JSON {action, status, cluster, changes}.
    """
    if msg := _gate("cluster.ops"):
        return msg
    if enabled is None and behavior is None and vmotion_rate is None:
        return "Error: provide at least one of enabled, behavior or vmotion_rate."
    if behavior is not None and behavior not in DRS_BEHAVIORS:
        return f"Error: invalid behavior '{behavior}'. Choose from: {', '.join(DRS_BEHAVIORS)}."
    try:
        c = find_cluster(cluster)
        drs = vim.cluster.DrsConfigInfo()
        changes: dict[str, Any] = {}
        if enabled is not None:
            drs.enabled = enabled
            changes["enabled"] = enabled
        if behavior is not None:
            drs.defaultVmBehavior = getattr(vim.cluster.DrsConfigInfo.DrsBehavior, behavior)
            changes["behavior"] = behavior
        if vmotion_rate is not None:
            drs.vmotionRate = vmotion_rate
            changes["vmotion_rate"] = vmotion_rate
        spec = vim.cluster.ConfigSpecEx(drsConfig=drs)
        wait_for_task(c.ReconfigureComputeResource_Task(spec, True))
        return {"action": "set_drs", "status": "success", "cluster": c.name, "changes": changes}
    except Exception as e:
        return error_text(e)


@tool("vmware_set_ha", "Configure HA", group="cluster.ops")
def vmware_set_ha(
    cluster: Annotated[str, Field(description="Cluster name")],
    enabled: Annotated[bool, Field(description="Enable (true) or disable (false) HA")],
    admission_control: Annotated[
        bool | None, Field(description="Enable admission control (failover capacity)")
    ] = None,
) -> dict[str, Any] | str:
    """Enables or disables vSphere HA (DAS) on a cluster.

    Returns a JSON {action, status, cluster, changes}.
    """
    if msg := _gate("cluster.ops"):
        return msg
    try:
        c = find_cluster(cluster)
        das = vim.cluster.DasConfigInfo(enabled=enabled)
        changes: dict[str, Any] = {"enabled": enabled}
        if admission_control is not None:
            das.admissionControlEnabled = admission_control
            changes["admission_control"] = admission_control
        spec = vim.cluster.ConfigSpecEx(dasConfig=das)
        wait_for_task(c.ReconfigureComputeResource_Task(spec, True))
        return {"action": "set_ha", "status": "success", "cluster": c.name, "changes": changes}
    except Exception as e:
        return error_text(e)


@tool("vmware_apply_drs_recommendation", "Apply a DRS recommendation", group="cluster.ops")
def vmware_apply_drs_recommendation(
    cluster: Annotated[str, Field(description="Cluster name")],
    key: Annotated[str, Field(description="Recommendation key (see vmware_drs_recommendations)")],
) -> dict[str, Any] | str:
    """Applies a pending DRS recommendation (triggers the proposed migrations).

    Returns a JSON {action, status, cluster, key}.
    """
    if msg := _gate("cluster.ops"):
        return msg
    try:
        c = find_cluster(cluster)
        known = [r.key for r in c.recommendation or []]
        if key not in known:
            return (
                f"Error: recommendation '{key}' unknown on '{c.name}'. "
                f"Pending keys: {', '.join(known) or 'none'}."
            )
        c.ApplyRecommendation(key)
        return {
            "action": "apply_drs_recommendation",
            "status": "success",
            "cluster": c.name,
            "key": key,
        }
    except Exception as e:
        return error_text(e)


@tool("vmware_set_affinity_rule", "Create/delete an affinity rule", group="cluster.ops")
def vmware_set_affinity_rule(
    cluster: Annotated[str, Field(description="Cluster name")],
    action: Annotated[str, Field(description="create or delete")],
    name: Annotated[str, Field(min_length=1, max_length=80, description="Rule name")],
    rule_type: Annotated[
        str,
        Field(
            description="affinity (VMs kept together) or anti_affinity (VMs kept apart). "
            "Required for create."
        ),
    ] = "anti_affinity",
    vms: Annotated[
        list[str] | None,
        Field(description="Target VMs (names or MoIDs), minimum 2. Required for create."),
    ] = None,
) -> dict[str, Any] | str:
    """Creates or deletes a VM-VM affinity/anti-affinity rule on a cluster.

    Returns a JSON {action, status, cluster, rule}.
    """
    if msg := _gate("cluster.ops"):
        return msg
    if action not in ("create", "delete"):
        return "Error: invalid action, choose create or delete."
    if rule_type not in ("affinity", "anti_affinity"):
        return "Error: invalid rule_type, choose affinity or anti_affinity."
    try:
        c = find_cluster(cluster)
        if action == "delete":
            match = [r for r in (c.configurationEx.rule or []) if r.name == name]
            if not match:
                return f"Error: rule '{name}' not found on '{c.name}' (vmware_list_affinity_rules)."
            rule_spec = vim.cluster.RuleSpec(operation="remove", removeKey=match[0].key)
        else:
            if not vms or len(vms) < 2:
                return "Error: create requires at least 2 VMs."
            vm_objs = [find_vm(v) for v in vms]
            info_cls = (
                vim.cluster.AffinityRuleSpec
                if rule_type == "affinity"
                else vim.cluster.AntiAffinityRuleSpec
            )
            info = info_cls(name=name, enabled=True, vm=vm_objs)
            rule_spec = vim.cluster.RuleSpec(operation="add", info=info)
        spec = vim.cluster.ConfigSpecEx(rulesSpec=[rule_spec])
        wait_for_task(c.ReconfigureComputeResource_Task(spec, True))
        return {"action": f"rule_{action}", "status": "success", "cluster": c.name, "rule": name}
    except Exception as e:
        return error_text(e)
