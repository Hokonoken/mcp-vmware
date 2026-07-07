# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Hokonoken

"""Gestion de la session vCenter : connexion paresseuse et reconnexion.

Les identifiants sont lus depuis un fichier env (defaut ~/VMware/.vcenter.env,
surchargable par MCP_VMWARE_ENV_FILE) :
    VC_HOST=vcenter.example.com
    VC_USER=user@domaine
    VC_PASS=...
    MCP_VMWARE_ROLE=viewer|operator|vm_admin|infra_admin   (defaut viewer, cf. roles.py)
"""

import atexit
import contextlib
import os
import ssl
import threading

from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim

ENV_FILE = os.environ.get("MCP_VMWARE_ENV_FILE", os.path.expanduser("~/VMware/.vcenter.env"))

_lock = threading.Lock()
_si: vim.ServiceInstance | None = None


def load_env() -> None:
    if not os.path.exists(ENV_FILE):
        return
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)


def _connect() -> vim.ServiceInstance:
    load_env()
    missing = [k for k in ("VC_HOST", "VC_USER", "VC_PASS") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Variables manquantes: {', '.join(missing)}. "
            f"Renseigner {ENV_FILE} (VC_HOST/VC_USER/VC_PASS)."
        )
    ctx = ssl._create_unverified_context()
    return SmartConnect(
        host=os.environ["VC_HOST"],
        user=os.environ["VC_USER"],
        pwd=os.environ["VC_PASS"],
        sslContext=ctx,
    )


def _session_alive(si: vim.ServiceInstance) -> bool:
    try:
        session_manager = si.content.sessionManager
        return session_manager is not None and session_manager.currentSession is not None
    except Exception:
        return False


def get_si() -> vim.ServiceInstance:
    """Retourne une session vCenter valide, en (re)connectant si necessaire."""
    global _si
    with _lock:
        if _si is None or not _session_alive(_si):
            _si = _connect()
        return _si


def _cleanup() -> None:
    global _si
    if _si is not None:
        with contextlib.suppress(Exception):
            Disconnect(_si)
        _si = None


atexit.register(_cleanup)
