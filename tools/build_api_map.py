#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Map the vCenter API surface, versioned by build.

Produces in api-map/<version>-<build>/ :
  - meta.json   : vCenter identity (version, build), date, tool versions
  - vim25.json  : full SOAP map (managed objects, properties, methods)
  - rest.json   : vAPI REST map (components -> services -> operations), read from the live vCenter
  - SUMMARY.md  : human-readable statistics

Runs on the jump machine (jumphost), in the ~/VMware/venv venv.
Usage: build_api_map.py [--out DIR]
"""

import argparse
import json
import os
import re
import ssl
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

READ_METHOD_RE = re.compile(
    r"^(get|query|read|retrieve|list|find|fetch|lookup|check|has|browse|search|open|export|"
    r"estimate|validate|scan|generate[A-Z].*[Rr]eport|acquire[A-Z].*[Tt]icket)",
)

ENV_FILE = os.path.expanduser("~/VMware/.vcenter.env")


def load_env(path: str) -> None:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)


def classify(method_name: str) -> str:
    return "read" if READ_METHOD_RE.match(method_name) else "write"


# ---------------------------------------------------------------- vim25 (SOAP)


def type_name(t: object) -> str:
    if isinstance(t, str):
        return t
    return getattr(t, "__name__", repr(t))


def build_vim25_map() -> dict:
    import pyVmomi.VmomiSupport as VS

    objects = {}
    for vmodl_name, definition in sorted(VS._managedDefMap.items()):
        # definition: [vmodlName, wsdlName, parent, version, props, methods]
        _, wsdl_name, parent, since, props, methods = (list(definition) + [None] * 6)[:6]
        prop_list = []
        for p in props or []:
            p = list(p)
            prop_list.append({"name": p[0], "type": type_name(p[1])})
        method_list = []
        for m in methods or []:
            m = list(m)
            name = m[0]
            params = []
            for prm in m[3] or []:
                prm = list(prm)
                params.append({"name": prm[0], "type": type_name(prm[1])})
            result = None
            if len(m) > 4 and m[4]:
                r = list(m[4]) if isinstance(m[4], (list, tuple)) else [m[4]]
                for item in r:
                    if isinstance(item, str) and item not in ("void",):
                        result = item
                        break
                if result is None and r:
                    result = type_name(r[-1])
            method_list.append(
                {
                    "name": name,
                    "kind": classify(name),
                    "params": params,
                    "result": result,
                }
            )
        objects[vmodl_name] = {
            "wsdl": wsdl_name,
            "parent": parent,
            "since": since,
            "properties": prop_list,
            "methods": method_list,
        }
    return objects


# ----------------------------------------------------------------- REST (vAPI)


class VapiClient:
    def __init__(self, host: str, user: str, password: str) -> None:
        self.base = f"https://{host}"
        self.s = requests.Session()
        self.s.verify = False
        r = self.s.post(f"{self.base}/api/session", auth=(user, password), timeout=30)
        r.raise_for_status()
        self.s.headers["vmware-api-session-id"] = r.json()

    def get(self, path: str) -> dict:
        r = self.s.get(f"{self.base}{path}", timeout=60)
        r.raise_for_status()
        return r.json()


def build_rest_map(client: VapiClient) -> dict:
    components = client.get("/rest/com/vmware/vapi/metadata/metamodel/component")["value"]
    rest = {}
    for comp in sorted(components):
        try:
            data = client.get(f"/rest/com/vmware/vapi/metadata/metamodel/component/id:{comp}")[
                "value"
            ]
        except requests.HTTPError as e:
            rest[comp] = {"error": str(e)}
            continue
        services = {}
        info = data.get("info", data)
        for pkg in info.get("packages", []):
            pkg_val = pkg.get("value", pkg)
            for svc in pkg_val.get("services", []):
                svc_val = svc.get("value", svc)
                svc_name = svc.get("key") or svc_val.get("name", "?")
                ops = []
                for op in svc_val.get("operations", []):
                    op_val = op.get("value", op)
                    op_name = op.get("key") or op_val.get("name", "?")
                    ops.append(
                        {
                            "name": op_name,
                            "kind": classify(op_name),
                            "params": [p.get("name", "?") for p in op_val.get("params", [])],
                        }
                    )
                if ops:
                    services[svc_name] = ops
        rest[comp] = {"services": services}
    return rest


# ---------------------------------------------------------------------- meta


def get_vcenter_identity() -> dict:
    from pyVim.connect import Disconnect, SmartConnect

    ctx = ssl._create_unverified_context()
    si = SmartConnect(
        host=os.environ["VC_HOST"],
        user=os.environ["VC_USER"],
        pwd=os.environ["VC_PASS"],
        sslContext=ctx,
    )
    about = si.content.about
    ident = {
        "fullName": about.fullName,
        "version": about.version,
        "build": about.build,
        "apiVersion": about.apiVersion,
        "instanceUuid": about.instanceUuid,
    }
    Disconnect(si)
    return ident


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.expanduser("~/VMware/api-map"))
    args = parser.parse_args()

    load_env(ENV_FILE)
    import pyVmomi

    ident = get_vcenter_identity()
    tag = f"{ident['version']}-{ident['build']}"
    out = Path(args.out) / tag
    out.mkdir(parents=True, exist_ok=True)

    meta = {
        "vcenter": ident,
        "snapshotDate": datetime.now(UTC).isoformat(),
        "pyvmomiVersion": getattr(pyVmomi, "__version__", "?"),
        "python": sys.version.split()[0],
        "note": "kind (read/write) is a heuristic based on the method/operation name",
    }

    vim25 = build_vim25_map()
    client = VapiClient(os.environ["VC_HOST"], os.environ["VC_USER"], os.environ["VC_PASS"])
    rest = build_rest_map(client)

    n_methods = sum(len(o["methods"]) for o in vim25.values())
    n_read = sum(1 for o in vim25.values() for m in o["methods"] if m["kind"] == "read")
    n_svc = sum(len(c.get("services", {})) for c in rest.values() if isinstance(c, dict))
    n_ops = sum(
        len(ops)
        for c in rest.values()
        if isinstance(c, dict)
        for ops in c.get("services", {}).values()
    )
    meta["stats"] = {
        "vim25_managed_objects": len(vim25),
        "vim25_methods": n_methods,
        "vim25_methods_read": n_read,
        "vim25_methods_write": n_methods - n_read,
        "rest_components": len(rest),
        "rest_services": n_svc,
        "rest_operations": n_ops,
    }

    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    (out / "vim25.json").write_text(json.dumps(vim25, indent=2))
    (out / "rest.json").write_text(json.dumps(rest, indent=2))

    summary = f"""# vCenter API map — {tag}

- vCenter: {ident["fullName"]}
- API version: {ident["apiVersion"]}
- Snapshot: {meta["snapshotDate"]}
- pyvmomi: {meta["pyvmomiVersion"]}

## SOAP surface (vim25)
- Managed objects: {len(vim25)}
- Methods: {n_methods} ({n_read} read / {n_methods - n_read} write, heuristic)

## REST surface (vAPI)
- Components: {len(rest)}
- Services: {n_svc}
- Operations: {n_ops}
"""
    (out / "SUMMARY.md").write_text(summary)
    print(f"Map generated in {out}")
    print(json.dumps(meta["stats"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
