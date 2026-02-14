"""Local deal folders reader - supplements Salesforce/Avoma with local files."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEALS_DIR = Path(__file__).resolve().parent.parent / "deals"


def read_deal_folders(deals_dir: Path | None = None) -> dict[str, dict[str, str]]:
    """Read all deal folders and return a dict of account_name -> {filename: content}.

    The folder name is treated as a normalized account name key.
    """
    deals_dir = deals_dir or DEALS_DIR
    if not deals_dir.is_dir():
        logger.info("No deals directory found at %s", deals_dir)
        return {}

    deals: dict[str, dict[str, str]] = {}

    for folder in sorted(deals_dir.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue

        account_key = folder.name.lower().replace("-", " ").replace("_", " ")
        files: dict[str, str] = {}

        for f in sorted(folder.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                try:
                    content = f.read_text(errors="replace")
                    # Limit to 5000 chars per file to avoid overwhelming the context
                    files[f.name] = content[:5000]
                except Exception as exc:
                    logger.warning("Could not read %s: %s", f, exc)

        if files:
            deals[account_key] = files
            logger.debug("Local deals: loaded %d files for '%s'", len(files), account_key)

    logger.info("Local deals: loaded %d accounts from %s", len(deals), deals_dir)
    return deals
