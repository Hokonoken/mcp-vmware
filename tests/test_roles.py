"""Roles, groupes de droits et messages de refus."""

import mcp_vmware.roles as roles


def test_role_par_defaut_est_viewer():
    assert roles.current_role() == "viewer"


def test_role_explicite(monkeypatch):
    for role in roles.ROLES:
        monkeypatch.setenv("MCP_VMWARE_ROLE", role)
        assert roles.current_role() == role


def test_role_inconnu_retombe_sur_viewer(monkeypatch):
    monkeypatch.setenv("MCP_VMWARE_ROLE", "superadmin")
    assert roles.current_role() == "viewer"


def test_role_insensible_casse_et_espaces(monkeypatch):
    monkeypatch.setenv("MCP_VMWARE_ROLE", "  Infra_Admin ")
    assert roles.current_role() == "infra_admin"


def test_compat_allow_write_donne_vm_admin(monkeypatch):
    monkeypatch.setenv("MCP_VMWARE_ALLOW_WRITE", "1")
    assert roles.current_role() == "vm_admin"


def test_role_explicite_prime_sur_allow_write(monkeypatch):
    monkeypatch.setenv("MCP_VMWARE_ALLOW_WRITE", "1")
    monkeypatch.setenv("MCP_VMWARE_ROLE", "viewer")
    assert roles.current_role() == "viewer"


def test_hierarchie_des_roles_est_croissante():
    ordre = ["viewer", "operator", "vm_admin", "infra_admin"]
    for inferieur, superieur in zip(ordre, ordre[1:], strict=False):
        assert roles.ROLES[inferieur] < roles.ROLES[superieur]


def test_infra_admin_couvre_tous_les_groupes():
    assert roles.ROLES["infra_admin"] == frozenset(roles.GROUPS)


def test_matrice_group_allowed(monkeypatch):
    cas = [
        ("viewer", "read", True),
        ("viewer", "vm.power", False),
        ("operator", "vm.power", True),
        ("operator", "vm.lifecycle", False),
        ("vm_admin", "vm.lifecycle", True),
        ("vm_admin", "cluster.ops", False),
        ("infra_admin", "host.config", True),
    ]
    for role, group, attendu in cas:
        monkeypatch.setenv("MCP_VMWARE_ROLE", role)
        assert roles.group_allowed(group) is attendu, (role, group)


def test_deny_message_est_actionnable(monkeypatch):
    monkeypatch.setenv("MCP_VMWARE_ROLE", "viewer")
    msg = roles.deny_message("host.ops")
    assert "viewer" in msg
    assert "host.ops" in msg
    assert "infra_admin" in msg
    assert "MCP_VMWARE_ROLE" in msg


def test_tous_les_groupes_sont_atteignables():
    couverts = set()
    for groups in roles.ROLES.values():
        couverts |= groups
    assert couverts == set(roles.GROUPS)
