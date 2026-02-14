"""Credential management - interactive setup and secure .env storage."""

import os
from getpass import getpass
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

REQUIRED_KEYS = [
    ("SALESFORCE_USERNAME", "Salesforce username (email)", False),
    ("SALESFORCE_PASSWORD", "Salesforce password", True),
    ("SALESFORCE_SECURITY_TOKEN", "Salesforce security token", True),
    ("MY_SALESFORCE_EMAIL", "Your Salesforce email (to filter your opps)", False),
    ("AVOMA_API_KEY", "Avoma API key", True),
    ("ANTHROPIC_API_KEY", "Anthropic (Claude) API key", True),
]


def load_credentials() -> dict[str, str]:
    """Load credentials from .env file. Returns dict of key -> value."""
    load_dotenv(ENV_PATH)
    return {key: os.getenv(key, "") for key, _, _ in REQUIRED_KEYS}


def credentials_complete(creds: dict[str, str]) -> bool:
    """Check if all required credentials are present."""
    return all(creds.get(key) for key, _, _ in REQUIRED_KEYS)


def interactive_setup() -> dict[str, str]:
    """Prompt user for missing credentials and write to .env file."""
    print("\n" + "=" * 50)
    print("  DEAL COMMAND CENTER - First-Time Setup")
    print("=" * 50)
    print("\nI need a few API credentials to get started.")
    print("These will be saved securely in a local .env file.\n")

    creds = load_credentials()
    existing_lines: dict[str, str] = {}

    # Read existing .env to preserve comments and order
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                existing_lines[k] = line

    changed = False
    for key, description, is_secret in REQUIRED_KEYS:
        current = creds.get(key)
        if current:
            masked = current[:3] + "***" if len(current) > 3 else "***"
            print(f"  {description}: {masked} (already set)")
            continue

        if is_secret:
            value = getpass(f"  {description}: ")
        else:
            value = input(f"  {description}: ")

        value = value.strip()
        if not value:
            print(f"    Skipping {key} (empty). You can set it later in .env")
            continue

        creds[key] = value
        existing_lines[key] = f"{key}={value}"
        changed = True

    if changed:
        # Write .env preserving existing structure
        lines = []
        written_keys = set()
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text().splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k = stripped.split("=", 1)[0].strip()
                    if k in existing_lines:
                        lines.append(existing_lines[k])
                        written_keys.add(k)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)

        # Append any new keys not already in the file
        for key in existing_lines:
            if key not in written_keys:
                lines.append(existing_lines[key])

        ENV_PATH.write_text("\n".join(lines) + "\n")
        print(f"\n  Credentials saved to {ENV_PATH}")

    # Reload to make sure env vars are set
    load_dotenv(ENV_PATH, override=True)
    creds = {key: os.getenv(key, "") for key, _, _ in REQUIRED_KEYS}
    return creds


def ensure_credentials() -> dict[str, str]:
    """Load credentials, running interactive setup if any are missing."""
    creds = load_credentials()
    if not credentials_complete(creds):
        creds = interactive_setup()
    return creds
