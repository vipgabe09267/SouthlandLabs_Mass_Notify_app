"""Stable compatibility identities used by installations before the rebrand.

These values are not presentation strings. Renaming them would orphan saved
credentials, enrollment history, downloaded voices, or an interrupted upgrade.
New windows, executable names, metadata and clean-install paths use the current
Southland Labs identity instead.
"""
from pathlib import Path
import os

APP_SHORT_NAME = "SLS_Mass_Notify"
COMPANY_NAME = "SouthlandServers"
APP_DISPLAY_NAME = "SouthlandServers Mass Notification App"
COMPANY_DISPLAY_NAME = "Southland Servers Group"
EXE_NAME = "SLS_Mass_Notify.exe"
INSTALLER_EXE_NAME = "SLS_Mass_Notify_Uninstall.exe"
SETUP_EXE_NAME = "SLS_Mass_Notify_Installer.exe"
CREDENTIAL_TARGET_PREFIX = COMPANY_NAME + "/" + APP_SHORT_NAME
SINGLE_INSTANCE_MUTEX = "Local\\" + APP_SHORT_NAME + "_SingleInstance"
PRODUCT_ID = "SouthlandServers.SLSMassNotify"
MANIFEST_NAME = ".sls-install-manifest.json"
TRANSACTION_NAME = ".sls-install-transaction.json"
BACKUP_PREFIX = ".sls-backup-"
UNINSTALL_REG_PATH = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + APP_SHORT_NAME
RUN_VALUE_NAME = APP_SHORT_NAME
UPDATE_FILE_PREFIX = "SLS_Update_"


def config_directory() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / COMPANY_NAME / APP_SHORT_NAME


def voice_cache_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / COMPANY_NAME / APP_SHORT_NAME / "voices"


def machine_shortcuts() -> dict[str, Path]:
    programs = (Path(os.environ.get("ProgramData", r"C:\ProgramData"))
                / "Microsoft/Windows/Start Menu/Programs")
    return {
        "application": programs / COMPANY_DISPLAY_NAME / f"{APP_DISPLAY_NAME}.lnk",
        "uninstall": programs / COMPANY_DISPLAY_NAME / f"Uninstall {APP_DISPLAY_NAME}.lnk",
        "startup": programs / "Startup" / f"{APP_DISPLAY_NAME}.lnk",
    }
