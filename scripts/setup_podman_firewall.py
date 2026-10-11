#!/usr/bin/env python3
"""Install scoped IPv4 forwarding exceptions for rootful Podman beside Docker."""

import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CHAIN = "AMATERASU-PODMAN"
INSTALLED = Path("/usr/local/libexec/amaterasu-podman-firewall.py")
UNITS = Path("/etc/systemd/system")
UNIT = "amaterasu-podman-firewall"
SERVICE = f"""[Unit]
Description=Allow Amaterasu Podman forwarding alongside Docker
After=docker.service podman.service network-online.target

[Service]
Type=oneshot
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/usr/bin/env python3 {INSTALLED.as_posix()} --apply
TimeoutStartSec=30
"""
TIMER = """[Unit]
Description=Maintain Amaterasu Podman forwarding exceptions

[Timer]
OnBootSec=5s
OnUnitInactiveSec=15s
AccuracySec=1s

[Install]
WantedBy=timers.target
"""


def command(*args, **kwargs):
    return subprocess.run(
        args, text=True, capture_output=True, check=True, timeout=10, **kwargs
    ).stdout


def rules_for(network):
    if network["name"] != "podman" or network["driver"] != "bridge":
        raise ValueError("Expected Podman's default bridge network")
    interface = network["network_interface"]
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", interface):
        raise ValueError("Invalid bridge interface")
    rules = []
    for container in network.get("containers", {}).values():
        if container["name"] != "amaterasu-bot":
            continue
        for attachment in container["interfaces"].values():
            for subnet in attachment["subnets"]:
                address = ipaddress.ip_interface(subnet["ipnet"]).ip
                if address.version != 4:
                    continue
                address = f"{address}/32"
                rules.extend(
                    [
                        f"-A {CHAIN} -i {interface} -s {address} -m conntrack "
                        "--ctstate NEW,ESTABLISHED,RELATED -j ACCEPT",
                        f"-A {CHAIN} -o {interface} -d {address} -m conntrack "
                        "--ctstate ESTABLISHED,RELATED -j ACCEPT",
                        # Only explicitly forwarded ports may accept new inbound traffic.
                        f"-A {CHAIN} -o {interface} -d {address} -m conntrack "
                        "--ctstate DNAT -j ACCEPT",
                    ]
                )
    return rules


def apply_rules():
    existing = command("iptables", "-w", "5", "-S").splitlines()
    if "-N DOCKER-USER" not in existing:
        return
    network = json.loads(command("podman", "network", "inspect", "podman"))[0]
    rules = rules_for(network)
    # Replace only our chain atomically, removing addresses from old containers.
    command(
        "iptables-restore",
        "--wait",
        "5",
        "--noflush",
        input="\n".join(["*filter", f":{CHAIN} - [0:0]", *rules, "COMMIT", ""]),
    )
    if f"-A DOCKER-USER -j {CHAIN}" not in existing:
        command("iptables", "-w", "5", "-I", "DOCKER-USER", "1", "-j", CHAIN)


def install():
    for program in ("podman", "iptables", "iptables-restore", "systemctl"):
        if not shutil.which(program):
            raise ValueError(f"Required host command missing: {program}")
    INSTALLED.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).resolve(), INSTALLED)
    INSTALLED.chmod(0o755)
    (UNITS / f"{UNIT}.service").write_text(SERVICE, encoding="utf-8")
    (UNITS / f"{UNIT}.timer").write_text(TIMER, encoding="utf-8")
    command("systemctl", "daemon-reload")
    command("systemctl", "enable", "--now", f"{UNIT}.timer")
    command("systemctl", "start", f"{UNIT}.service")
    print("Installed forwarding maintenance for amaterasu-bot (every 15 seconds).")


if __name__ == "__main__":
    try:
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("Run on the VPS host with sudo python3")
        if sys.argv[1:] == ["--apply"]:
            apply_rules()
        elif not sys.argv[1:]:
            install()
        else:
            raise ValueError("Usage: sudo python3 scripts/setup_podman_firewall.py")
    except (ValueError, KeyError, IndexError, OSError, subprocess.SubprocessError) as error:
        print(f"Podman firewall setup failed: {error}", file=sys.stderr)
        sys.exit(1)
