from __future__ import annotations

import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

ProgressFn = Callable[[str, int, int], None]


class ToolError(RuntimeError):
    pass


def which_signalbackup_tools() -> Optional[str]:
    return shutil.which("signalbackup-tools")


def which_sigtop() -> Optional[str]:
    return shutil.which("sigtop")


def ensure_signalbackup_tools(progress: Optional[ProgressFn] = None) -> str:
    found = which_signalbackup_tools()
    if found:
        return found
    brew = shutil.which("brew")
    if not brew:
        raise ToolError(
            "signalbackup-tools is not installed. Install Homebrew, then "
            "brew install --HEAD bepaald/signalbackup-tools/signalbackup-tools"
        )
    if progress:
        progress("Installing signalbackup-tools", 0, 1)
    subprocess.run(
        [brew, "tap", "bepaald/signalbackup-tools", "https://github.com/bepaald/signalbackup-tools"],
        check=False,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [brew, "install", "--HEAD", "signalbackup-tools"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ToolError(result.stderr.strip() or "failed to install signalbackup-tools")
    found = which_signalbackup_tools()
    if not found:
        raise ToolError("signalbackup-tools installed but not on PATH")
    if progress:
        progress("Installing signalbackup-tools", 1, 1)
    return found


def close_signal_desktop() -> bool:
    sysname = platform.system().lower()
    try:
        if sysname == "darwin":
            subprocess.run(["osascript", "-e", 'tell application "Signal" to quit'], capture_output=True)
            subprocess.run(["pkill", "-x", "Signal"], capture_output=True)
        elif sysname == "windows":
            subprocess.run(["taskkill", "/IM", "Signal.exe", "/F"], capture_output=True)
        else:
            subprocess.run(["pkill", "-x", "signal-desktop"], capture_output=True)
            subprocess.run(["pkill", "-x", "Signal"], capture_output=True)
        time.sleep(1.5)
        return True
    except Exception:
        return False


def dump_desktop_db(
    dest: Path,
    *,
    desktop_dir: Optional[Path] = None,
    ignore_wal: bool = False,
    progress: Optional[ProgressFn] = None,
) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if progress:
        progress("Decrypting Signal database", 0, 1)

    tool = which_signalbackup_tools()
    if tool:
        cmd = [tool, "--dumpdesktopdb", str(dest), "--overwrite"]
        if desktop_dir:
            cmd.extend(["--desktopdir", str(desktop_dir)])
        if ignore_wal:
            cmd.append("--ignorewal")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise ToolError(result.stderr.strip() or result.stdout.strip() or "dumpdesktopdb failed")
    else:
        sigtop = which_sigtop()
        if not sigtop:
            tool = ensure_signalbackup_tools(progress)
            cmd = [tool, "--dumpdesktopdb", str(dest), "--overwrite"]
            if desktop_dir:
                cmd.extend(["--desktopdir", str(desktop_dir)])
            if ignore_wal:
                cmd.append("--ignorewal")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise ToolError(result.stderr.strip() or "dumpdesktopdb failed")
        else:
            cmd = [sigtop, "db", str(dest)]
            if desktop_dir:
                cmd.extend(["-d", str(desktop_dir)])
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise ToolError(result.stderr.strip() or "sigtop db failed")

    if not dest.exists() or dest.stat().st_size == 0:
        raise ToolError("decrypted database was not created")
    if progress:
        progress("Decrypting Signal database", 1, 1)
    return dest


def describe_providers() -> dict[str, Optional[str]]:
    return {
        "signalbackup-tools": which_signalbackup_tools(),
        "sigtop": which_sigtop(),
    }
