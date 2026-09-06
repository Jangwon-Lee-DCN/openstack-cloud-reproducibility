#!/usr/bin/env python3
import argparse
import json
import subprocess


START = "# BEGIN DCN AUTHORITATIVE FORWARD"
END = "# END DCN AUTHORITATIVE FORWARD"


def kubectl(*args, input_text=None):
    return subprocess.run(
        ["kubectl", *args], input=input_text, text=True, check=True,
        capture_output=True,
    ).stdout


def render_corefile(corefile, zone, servers):
    if START in corefile:
        prefix, remainder = corefile.split(START, 1)
        _, suffix = remainder.split(END, 1)
        corefile = (prefix.rstrip() + "\n" + suffix.lstrip()).strip() + "\n"
    block = (
        f"{START}\n{zone}:53 {{\n"
        f"    errors\n    cache 30\n    forward . {' '.join(servers)}\n"
        f"}}\n{END}\n"
    )
    return block + corefile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zone", required=True)
    parser.add_argument("--server", action="append", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    current = json.loads(kubectl("-n", "kube-system", "get", "configmap", "coredns", "-o", "json"))
    desired = render_corefile(current["data"]["Corefile"], args.zone, args.server)
    if desired == current["data"]["Corefile"]:
        print("CoreDNS authoritative forward already reconciled")
        return
    if args.check:
        print("CoreDNS authoritative forward requires reconciliation")
        return
    patch = json.dumps({"data": {"Corefile": desired}})
    kubectl("-n", "kube-system", "patch", "configmap", "coredns", "--type=merge", "-p", patch)
    print("CoreDNS authoritative forward reconciled")


if __name__ == "__main__":
    main()
