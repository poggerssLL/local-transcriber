"""Portable download names derived from user-visible recording titles."""

from __future__ import annotations

import re
import unicodedata


def download_filename(title: str, extension: str) -> str:
    name = unicodedata.normalize("NFC", title)
    name = "".join("-" if unicodedata.category(char).startswith("C") else char for char in name)
    name = re.sub(r'[<>:"/\\|?*]', "-", name).strip(" .")
    # Leave room for the extension even on filesystems with a 255-byte limit.
    name = name.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip(" .")
    name = name or "transcricao"
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    if name.split(".", 1)[0].upper() in reserved:
        name = "_" + name
    return f"{name}.{extension}"
