"""Check scoped firewall maintenance without changing the host firewall."""

import importlib.util
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "podman_firewall",
    Path(__file__).resolve().parents[1] / "scripts/setup_podman_firewall.py",
)
firewall = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(firewall)


def network(address="10.88.0.2/16"):
    return {
        "name": "podman",
        "driver": "bridge",
        "network_interface": "podman0",
        "containers": {
            "bot-id": {
                "name": "amaterasu-bot",
                "interfaces": {"eth0": {"subnets": [{"ipnet": address}]}},
            },
            "other-id": {
                "name": "another-container",
                "interfaces": {"eth0": {"subnets": [{"ipnet": "10.88.0.3/16"}]}},
            },
        },
    }


class Host:
    def __init__(self):
        self.network = network()
        self.chains = {"DOCKER-USER"}
        self.jumps = []
        self.rules = []
        self.calls = []
        self.fail_inspect = False

    def command(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if args == ("iptables", "-w", "5", "-S"):
            return "\n".join(["-P FORWARD DROP", *(f"-N {c}" for c in self.chains), *self.jumps])
        if args == ("podman", "network", "inspect", "podman"):
            if self.fail_inspect:
                raise subprocess.CalledProcessError(1, args)
            return json.dumps([self.network])
        if args == ("iptables-restore", "--wait", "5", "--noflush"):
            lines = kwargs["input"].splitlines()
            assert lines[0] == "*filter" and lines[-1] == "COMMIT"
            assert lines[1] == f":{firewall.CHAIN} - [0:0]"
            assert all(line.startswith(f"-A {firewall.CHAIN} ") for line in lines[2:-1])
            self.rules = lines[2:-1]
            self.chains.add(firewall.CHAIN)
        elif args == ("iptables", "-w", "5", "-I", "DOCKER-USER", "1", "-j", firewall.CHAIN):
            self.jumps.insert(0, f"-A DOCKER-USER -j {firewall.CHAIN}")
        else:
            raise AssertionError(f"Unexpected host mutation: {args}")
        return ""


def test_recreation_stop_and_firewall_reset_keep_rules_scoped(monkeypatch):
    host = Host()
    monkeypatch.setattr(firewall, "command", host.command)
    firewall.apply_rules()
    assert len(host.rules) == 3
    assert all("10.88.0.2/32" in rule and "podman0" in rule for rule in host.rules)
    assert "--ctstate ESTABLISHED,RELATED" in host.rules[1]
    assert "--ctstate DNAT -j ACCEPT" in host.rules[2]
    firewall.apply_rules()
    assert len(host.jumps) == 1

    host.network = network("10.88.0.9/16")
    firewall.apply_rules()
    assert all("10.88.0.9/32" in rule for rule in host.rules)
    assert all("10.88.0.2" not in rule for rule in host.rules)

    host.network["containers"].pop("bot-id")
    firewall.apply_rules()
    assert host.rules == []

    host.network = network("10.88.0.10/16")
    host.chains = {"DOCKER-USER"}
    host.jumps = []
    firewall.apply_rules()
    assert len(host.jumps) == 1 and len(host.rules) == 3
    assert all("10.88.0.10/32" in rule for rule in host.rules)


def test_no_docker_chain_leaves_firewall_alone(monkeypatch):
    host = Host()
    host.chains.clear()
    monkeypatch.setattr(firewall, "command", host.command)
    firewall.apply_rules()
    assert len(host.calls) == 1


def test_inspect_failure_preserves_existing_rules(monkeypatch):
    host = Host()
    monkeypatch.setattr(firewall, "command", host.command)
    firewall.apply_rules()
    old_rules = deepcopy(host.rules)
    host.fail_inspect = True
    with pytest.raises(subprocess.CalledProcessError):
        firewall.apply_rules()
    assert host.rules == old_rules


@pytest.mark.parametrize(
    "field,value",
    [
        ("network_interface", "podman0\n-j ACCEPT"),
        ("driver", "macvlan"),
        ("name", "another-network"),
    ],
)
def test_invalid_network_cannot_change_firewall(monkeypatch, field, value):
    host = Host()
    host.network[field] = value
    monkeypatch.setattr(firewall, "command", host.command)
    with pytest.raises(ValueError):
        firewall.apply_rules()
    assert len(host.calls) == 2


def test_ipv6_has_no_unscoped_ipv4_exception():
    assert firewall.rules_for(network("fd00::2/64")) == []
    with pytest.raises(ValueError):
        firewall.rules_for(network("bad-address"))


def test_installer_uses_root_owned_copy_and_enables_repeating_timer(monkeypatch, tmp_path):
    installed = tmp_path / "libexec" / "firewall.py"
    units = tmp_path / "units"
    units.mkdir()
    calls = []
    monkeypatch.setattr(firewall, "INSTALLED", installed)
    monkeypatch.setattr(firewall, "UNITS", units)
    monkeypatch.setattr(firewall.shutil, "which", lambda program: f"/usr/bin/{program}")
    monkeypatch.setattr(firewall, "command", lambda *args: calls.append(args))
    firewall.install()
    assert installed.read_bytes() == Path(firewall.__file__).read_bytes()
    service = (units / f"{firewall.UNIT}.service").read_text()
    timer = (units / f"{firewall.UNIT}.timer").read_text()
    assert "/usr/local/libexec/amaterasu-podman-firewall.py --apply" in service
    assert "OnBootSec=5s" in timer and "OnUnitInactiveSec=15s" in timer
    assert "RemainAfterExit" not in service
    assert calls == [
        ("systemctl", "daemon-reload"),
        ("systemctl", "enable", "--now", f"{firewall.UNIT}.timer"),
        ("systemctl", "start", f"{firewall.UNIT}.service"),
    ]


def test_missing_host_tool_does_not_install(monkeypatch, tmp_path):
    installed = tmp_path / "firewall.py"
    monkeypatch.setattr(firewall, "INSTALLED", installed)
    monkeypatch.setattr(firewall.shutil, "which", lambda program: None)
    with pytest.raises(ValueError, match="podman"):
        firewall.install()
    assert not installed.exists()
