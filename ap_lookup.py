#!/usr/bin/env python3
"""
ap_lookup.py
Logs into one or more Cisco switches via Netmiko, runs 'show cdp neighbors',
and reports any FAU access points found in the neighbor table.

AP name format: <campus><bldg#><bldg-letters><room>ap<jack>
  e.g.  boc10ad104ap1533

Credential file format (switch-credentials.txt):
    Username:          <username>
    Password:          <password>
    Secret:            <secret>
    SecondaryUsername: <username>   (optional)
    SecondaryPassword: <password>   (optional)
"""

import re
import sys
from pathlib import Path
from netmiko import ConnectHandler, NetmikoAuthenticationException, NetmikoTimeoutException

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
_BASE    = Path(r"C:\Users\elija\OneDrive\Documents\Networking\Switches\scripts")
CRED_FILE = _BASE / "credentials" / "switch-credentials.txt"


# ---------------------------------------------------------------------------
# Credential loader
# ---------------------------------------------------------------------------
def parse_credentials(path: Path) -> dict:
    """
    Parse the switch credentials file.
    Returns a dict with keys: username, password, secret,
    and optionally secondary_username, secondary_password.
    """
    creds = {}
    key_map = {
        "username":          "username",
        "password":          "password",
        "secret":            "secret",
        "secondaryusername": "secondary_username",
        "secondarypassword": "secondary_password",
    }
    if not path.exists():
        sys.exit(f"[ERROR] Credentials file not found: {path}")
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                raw_key, _, value = line.partition(":")
                key = raw_key.strip().lower().replace(" ", "")
                if key in key_map:
                    creds[key_map[key]] = value.strip()
    for required in ("username", "password", "secret"):
        if required not in creds:
            sys.exit(f"[ERROR] Missing required credential field: '{required}'")
    return creds

# ---------------------------------------------------------------------------
# AP name pattern  —  e.g. boc10ad104ap1533
#   campus        : 2-4 lowercase letters          (boc / dav / jup …)
#   building num  : 1-3 digits                     (10)
#   building alpha: 1-4 lowercase letters          (ad)
#   room          : 1-4 digits                     (104)
#   literal "ap"
#   jack          : 1-6 digits                     (1533)
# ---------------------------------------------------------------------------
AP_PATTERN = re.compile(
    r'\b([a-z]{2,4}\d{1,3}[a-z]{1,4}\d{1,4}ap\d{1,6})\b',
    re.IGNORECASE
)


def collect_ips() -> list[str]:
    """Prompt the user to enter switch IPs one per line. Blank line ends input."""
    print("Enter switch IP addresses (one per line). Press Enter on a blank line when done:")
    ips: list[str] = []
    while True:
        line = input("> ").strip()
        if not line:
            if ips:
                break
            continue  # ignore leading blank lines
        # Support space- or comma-delimited entries on a single paste
        tokens = re.split(r'[,\s]+', line)
        for token in tokens:
            token = token.strip()
            if token:
                ips.append(token)
    return ips


def try_connect(ip: str, creds: dict) -> tuple:
    """
    Attempt connection with primary credentials, fall back to secondary.
    Returns (connection, username_used) or raises on total failure.
    """
    primary  = [(creds["username"], creds["password"])]
    secondary = []
    if "secondary_username" in creds and "secondary_password" in creds:
        secondary = [(creds["secondary_username"], creds["secondary_password"])]

    for user, pwd in primary + secondary:
        device = {
            "device_type": "cisco_ios",
            "host":        ip,
            "username":    user,
            "password":    pwd,
            "secret":      creds["secret"],
            "timeout":     15,
            "fast_cli":    False,
        }
        try:
            conn = ConnectHandler(**device)
            conn.enable()
            return conn, user
        except NetmikoAuthenticationException:
            continue  # try next credential set
        except NetmikoTimeoutException:
            raise NetmikoTimeoutException(f"Timed out connecting to {ip}")
    raise NetmikoAuthenticationException(
        f"All credential sets failed for {ip}"
    )


def find_aps_in_cdp(output: str) -> list[str]:
    """Return a sorted list of unique AP names found in CDP output."""
    matches = AP_PATTERN.findall(output)
    return sorted(set(m.lower() for m in matches))


def process_switch(ip: str, creds: dict) -> None:
    """Connect to a switch, run CDP, and print any APs found."""
    print(f"\n{'='*60}")
    print(f"  Switch: {ip}")
    print(f"{'='*60}")

    try:
        conn, user = try_connect(ip, creds)
        print(f"  [+] Connected as '{user}'")
    except (NetmikoAuthenticationException, NetmikoTimeoutException) as exc:
        print(f"  [!] Connection failed: {exc}")
        return

    try:
        output = conn.send_command("show cdp neighbors", read_timeout=30)
        conn.disconnect()
    except Exception as exc:
        print(f"  [!] Command error: {exc}")
        conn.disconnect()
        return

    aps = find_aps_in_cdp(output)

    if aps:
        print(f"  [+] Found {len(aps)} AP(s):")
        for ap in aps:
            print(f"        {ap}")
    else:
        print("  [-] No APs found in CDP neighbors.")


def main() -> None:
    creds = parse_credentials(CRED_FILE)
    ips = collect_ips()

    if not ips:
        print("No IPs provided. Exiting.")
        sys.exit(0)

    print(f"\nScanning {len(ips)} switch(es)...\n")

    # Echo back the list so the user can confirm the newline-per-IP display
    for ip in ips:
        print(f"  {ip}")

    print()
    confirm = input("Proceed? [Y/n]: ").strip().lower()
    if confirm not in ("", "y", "yes"):
        print("Aborted.")
        sys.exit(0)

    for ip in ips:
        process_switch(ip, creds)

    print(f"\n{'='*60}")
    print("  Scan complete.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
