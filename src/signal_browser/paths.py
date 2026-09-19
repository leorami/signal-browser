from __future__ import annotations

import os
import platform
from pathlib import Path


APP_NAME = "SignalBrowser"


def home_dir() -> Path:
    return Path(os.path.expanduser("~"))


def signal_data_dir() -> Path:
    sysname = platform.system().lower()
    home = home_dir()
    if sysname == "darwin":
        return home / "Library" / "Application Support" / "Signal"
    if sysname == "windows":
        appdata = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        return Path(appdata) / "Signal"
    flatpak = home / ".var" / "app" / "org.signal.Signal" / "config" / "Signal"
    if flatpak.exists():
        return flatpak
    return home / ".config" / "Signal"


def signal_attachments_dir() -> Path:
    return signal_data_dir() / "attachments.noindex"


def app_data_dir() -> Path:
    override = os.environ.get("SIGNAL_BROWSER_HOME")
    if override:
        return Path(os.path.expanduser(override))
    sysname = platform.system().lower()
    home = home_dir()
    if sysname == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    if sysname == "windows":
        appdata = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        return Path(appdata) / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "signal-browser"
    return home / ".local" / "share" / "signal-browser"


def vault_dir() -> Path:
    return app_data_dir() / "vault"


def window_state_path() -> Path:
    return app_data_dir() / "window.json"
