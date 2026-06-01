# ap_lookup.py

Connects to one or more Cisco switches via SSH, runs `show cdp neighbors`, and identifies any FAU access points present in the neighbor table.

---

## Requirements

### Python Version
Python 3.10 or later (uses `list[str]` type hints).

### Dependencies
Install via pip:
```
pip install netmiko
```

---

## Credentials File

The script does **not** store credentials in code. It reads from:

```
scripts/credentials/switch-credentials.txt
```

The file must follow this format exactly:

```
Username: <primary_username>
Password: <primary_password>
Secret: <enable_secret>
SecondaryUsername: <secondary_username>
SecondaryPassword: <secondary_password>
```

| Field               | Required | Description                                      |
|---------------------|----------|--------------------------------------------------|
| `Username`          | Yes      | Primary SSH login username                       |
| `Password`          | Yes      | Primary SSH login password                       |
| `Secret`            | Yes      | Enable mode secret (same for both credential sets) |
| `SecondaryUsername` | No       | Fallback username if primary auth fails          |
| `SecondaryPassword` | No       | Fallback password if primary auth fails          |

> **Note:** Lines starting with `#` are treated as comments and ignored.

---

## Directory Structure

The script expects the following folder layout relative to the `scripts/` root:

```
scripts/
├── python/
│   └── ap_lookup.py
├── credentials/
│   └── switch-credentials.txt
├── FiberStore Switch.txt
└── mist-mpls-template.txt
```

The base path is hardcoded near the top of the script:
```python
_BASE     = Path(r"C:\Users\elija\OneDrive\Documents\Networking\Switches\scripts")
CRED_FILE = _BASE / "credentials" / "switch-credentials.txt"
```

If you move the `scripts/` folder, update `_BASE` accordingly.

---

## Running the Script

```
python ap_lookup.py
```

Or, if you set up the `ap_lookup` shorthand (see below):

```
ap_lookup
```

---

## Usage

1. Run the script.
2. Enter switch IP addresses one per line. Press **Enter on a blank line** to finish.
   ```
   Enter switch IP addresses (one per line). Press Enter on a blank line when done:
   > <switch_ip_1>
   > <switch_ip_2>
   > <switch_ip_3>
   >
   ```
   You can also paste a space- or comma-separated list and the script will split it automatically.

3. The script echoes back your IP list and asks for confirmation before proceeding.

4. For each switch, it connects via SSH, runs `show cdp neighbors`, and prints any APs found.

---

## AP Name Format

The script detects APs matching the FAU naming convention:

```
<campus><building_number><building_letters><room>ap<jack>
```

**Example:** `<campus><building_number><building_letters><room>ap<jack>`

| Segment           | Example  | Description                        |
|-------------------|----------|------------------------------------|
| Campus            | `<campus>`    | 2–4 lowercase letters              |
| Building number   | `<building_number>`     | 1–3 digits                         |
| Building letters  | `<building_letters>`     | 1–4 lowercase letters              |
| Room              | `<room>`    | 1–4 digits                         |
| Literal `ap`      | `ap`     | Always present                     |
| Jack number       | `<jack>`   | 1–6 digits                         |

---

## Sample Output

```
============================================================
  Switch: <switch_ip_1>
============================================================
  [+] Connected as '<username>'
  [+] Found 3 AP(s):
        <ap_name_1>
        <ap_name_2>
        <ap_name_3>

============================================================
  Switch: <switch_ip_2>
============================================================
  [+] Connected as '<username>'
  [-] No APs found in CDP neighbors.

============================================================
  Scan complete.
============================================================
```

---

## Authentication Flow

The script tries credentials in this order:

1. **Primary** — `Username` / `Password` from the credentials file
2. **Secondary** — `SecondaryUsername` / `SecondaryPassword` (if present) — used automatically if primary auth fails

If both fail, the switch is skipped and the script moves on to the next IP.

---

## Setting Up the `ap_lookup` Shorthand (Windows)

To run the script by typing `ap_lookup` in any terminal or CMD window:

1. Create a folder for global scripts, e.g. `C:\tools`, and add it to your system `PATH`:
   - Search **"Edit the system environment variables"**
   - Click **Environment Variables**
   - Under **System variables**, select `Path` → **Edit** → **New**
   - Add `C:\tools`

2. Create `C:\tools\ap_lookup.bat` with the following content:
   ```bat
   @echo off
   python "C:\Users\elija\OneDrive\Documents\Networking\Switches\scripts\python\ap_lookup.py" %*
   ```

3. Open a new terminal and run:
   ```
   ap_lookup
   ```

> **PowerShell alternative:** Add this line to your PowerShell profile (`notepad $PROFILE`):
> ```powershell
> function ap_lookup { python "C:\Users\elija\OneDrive\Documents\Networking\Switches\scripts\python\ap_lookup.py" $args }
> ```
> This only works in PowerShell; the `.bat` approach works in both CMD and PowerShell.

---

## Troubleshooting

| Problem | Likely Cause | Fix |
|---|---|---|
| `[ERROR] Credentials file not found` | `switch-credentials.txt` is missing or path is wrong | Verify the file exists at `scripts/credentials/switch-credentials.txt` |
| `[ERROR] Missing required credential field: 'secret'` | `Secret:` line missing from credentials file | Add the `Secret:` field to the file |
| `[!] Connection failed: Authentication` | Wrong credentials or no secondary fallback | Check credentials file; ensure `SecondaryUsername`/`SecondaryPassword` are set if needed |
| `[!] Connection failed: Timed out` | Switch unreachable or SSH not enabled | Verify IP, check SSH is enabled on the switch (`ip ssh version 2`) |
| No APs found but you expect some | CDP name doesn't match FAU AP format | Try `show cdp neighbors detail` on the switch manually to check full hostnames; consider swapping the command in the script |

---

## Notes

- `show cdp neighbors` (short form) truncates device names longer than ~20 characters. If AP names are being cut off, edit the script and replace the command with `show cdp neighbors detail`, which always prints full hostnames.
- CDP must be enabled on the switch (`cdp run` globally, `cdp enable` per interface) for neighbors to appear.
- The script connects sequentially — one switch at a time. For large lists, runtime scales linearly with the number of switches and their response times.
