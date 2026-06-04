#!/usr/bin/env python3
"""
ap_lookup.py
Logs into one or more Cisco switches via Netmiko, runs 'show cdp neighbors',
and reports any FAU access points found in the neighbor table.

AP name format: <campus><bldg#><bldg-letters><room>ap<jack>
  e.g.  boc96en129ap1315c

Credential file format (switch-credentials.txt):
    Username:          <username>
    Password:          <password>
    Secret:            <secret>
    SecondaryUsername: <username>   (optional)
    SecondaryPassword: <password>   (optional)

Input accepts (case-insensitive):
    - Raw IP             : 10.10.22.255
    - Building number    : 22  /  building 22
    - Building range     : 20-25  /  building 20 - building 25
    - Mixed list         : 93, building 23, 5, 1, 100, 105
    - Campus name        : Jupiter / Davie / Harbor / FTL
"""

import re
import sys
from pathlib import Path
from netmiko import ConnectHandler, NetmikoAuthenticationException, NetmikoTimeoutException

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
_BASE     = Path(r"C:\Users\elija\OneDrive\Documents\Networking\Switches\scripts")
CRED_FILE = _BASE / "credentials" / "switch-credentials.txt"
SWITCH_DB = _BASE / "references"  / "switches2026.txt"

# ---------------------------------------------------------------------------
# Campus aliases — maps user input to section label in switches2026.txt
# ---------------------------------------------------------------------------
CAMPUS_ALIASES = {
    "jupiter":        "Jupiter",
    "jup":            "Jupiter",
    "harbor":         "Harbor",
    "har":            "Harbor",
    "ftl":            "FTL",
    "fortlauderdale": "FTL",
    "davie":          "Davie",
    "dav":            "Davie",
}

# Matches a building range like "20-25" or "building 20 - building 25"
BLDG_RANGE_RE = re.compile(
    r'^(?:building\s*)?(\d+)\s*-\s*(?:building\s*)?(\d+)$'
)

# Matches a single building like "22" or "building 22" (any case)
BLDG_SINGLE_RE = re.compile(
    r'^(?:building\s+)?(\d+)$'
)


# ---------------------------------------------------------------------------
# Switch database loader
# ---------------------------------------------------------------------------
def load_switch_db(path: Path) -> dict[str, list[str]]:
    """
    Parse switches2026.txt into a dict keyed by section label.
    e.g. { "Building 22": ["10.10.22.8", ...], "Jupiter": [...], ... }
    """
    if not path.exists():
        sys.exit(f"[ERROR] Switch database not found: {path}")

    db: dict[str, list[str]] = {}
    current = None
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1]
                db[current] = []
            elif current:
                db[current].append(line)
    return db


# ---------------------------------------------------------------------------
# Input resolver
# ---------------------------------------------------------------------------
def resolve_token(token: str, db: dict[str, list[str]]) -> list[str]:
    """
    Resolve a single user token to a list of IPs.
    Priority:
      1. Raw IP  (10.10.22.255)
      2. Building range  (20-25  /  building 20 - building 25)
      3. Single building  (22  /  building 22)
      4. Campus alias  (Jupiter, Davie, Harbor, FTL)
    """
    t = token.strip().lower()

    # 1. Raw IP — four octets
    if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', t):
        return [t]

    # 2. Building range
    m = BLDG_RANGE_RE.match(t)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        if start > end:
            start, end = end, start
        result = []
        for num in range(start, end + 1):
            key = f"Building {num}"
            if key in db:
                result.extend(db[key])
        if not result:
            print(f"  [!] No switches found for building range {start}-{end}.")
        return result

    # 3. Single building number (with or without "building " prefix, any case)
    m = BLDG_SINGLE_RE.match(t)
    if m:
        key = f"Building {m.group(1)}"
        if key in db:
            return db[key]
        print(f"  [!] No switches found for '{key}' in database.")
        return []

    # 4. Campus alias
    alias = CAMPUS_ALIASES.get(t.replace(" ", ""))
    if alias and alias in db:
        return db[alias]

    print(f"  [!] Could not resolve '{token}' — not a valid IP, building number, range, or campus name.")
    return []


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
# AP name pattern 1  —  FAU naming convention
#   e.g. boc96en129ap1315c  /  boc25fe113ap2/0/1
#   campus        : 2-4 lowercase letters
#   building num  : 1-3 digits
#   building alpha: 1-4 lowercase letters
#   room          : 1-4 digits
#   literal "ap"
#   jack          : numeric (opt. trailing letter)  OR  interface-style n/n/n
AP_NAME_PATTERN = re.compile(
    r'\b([a-z]{2,4}\d{1,3}[a-z]{1,4}\d{1,4}ap(?:\d+/\d+/\d+|\d{1,6}[a-z]?))',
    re.IGNORECASE
)

# AP name pattern 2  —  MAC-based default name
#   e.g. AP54fa.k12j.9487  ("AP" + three dotted hex groups)
AP_MAC_PATTERN = re.compile(
    r'\b(AP[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4})\b',
    re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Input collection
# ---------------------------------------------------------------------------
def collect_inputs() -> list[str]:
    """
    Prompt the user for IPs, building numbers/ranges, or campus names.
    One entry per line; blank line ends input.
    Comma or space delimiters on a single line are also accepted.
    """
    print("Enter switch IPs, building numbers, ranges, or campus names")
    print("(one per line, blank line when done):")
    print("  Examples: 10.10.22.255  |  22  |  building 22  |  20-25  |  Jupiter")

    tokens: list[str] = []
    while True:
        line = input("> ").strip()
        if not line:
            if tokens:
                break
            continue
        # Split on commas; keep "building XX - building YY" ranges intact
        # by only splitting on commas (not spaces) at the top level.
        parts = [p.strip() for p in line.split(",") if p.strip()]
        tokens.extend(parts)
    return tokens


# ---------------------------------------------------------------------------
# Netmiko helpers
# ---------------------------------------------------------------------------
def try_connect(ip: str, creds: dict) -> tuple:
    """Try primary then secondary credentials. Returns (conn, username)."""
    pairs = [(creds["username"], creds["password"])]
    if "secondary_username" in creds and "secondary_password" in creds:
        pairs.append((creds["secondary_username"], creds["secondary_password"]))

    for user, pwd in pairs:
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
            continue
        except NetmikoTimeoutException:
            raise NetmikoTimeoutException(f"Timed out connecting to {ip}")
    raise NetmikoAuthenticationException(f"All credential sets failed for {ip}")


def find_aps_in_cdp(output: str) -> list[str]:
    """Return a sorted, deduplicated list of AP names found in CDP output."""
    matches = AP_NAME_PATTERN.findall(output) + AP_MAC_PATTERN.findall(output)
    return sorted(set(m.lower() for m in matches))


def process_switch(ip: str, creds: dict) -> None:
    """Connect to a switch, run CDP neighbors, and print APs found."""
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    creds = parse_credentials(CRED_FILE)
    db    = load_switch_db(SWITCH_DB)

    raw_tokens = collect_inputs()
    if not raw_tokens:
        print("No input provided. Exiting.")
        sys.exit(0)

    # Resolve all tokens to IPs, preserving order, deduplicating
    seen: set[str] = set()
    ips:  list[str] = []
    for token in raw_tokens:
        for ip in resolve_token(token, db):
            if ip not in seen:
                seen.add(ip)
                ips.append(ip)

    if not ips:
        print("No valid IPs resolved. Exiting.")
        sys.exit(0)

    print(f"\nResolved {len(ips)} switch(es) to scan:")
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
