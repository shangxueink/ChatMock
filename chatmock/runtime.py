from __future__ import annotations

import json
import os
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any

from werkzeug.serving import WSGIRequestHandler, _log


DEFAULT_IP_REMARKS_FILE = "ip_remarks.json"
DEFAULT_BAD_GATEWAY_START = "00:00"
DEFAULT_BAD_GATEWAY_END = "00:30"


def _parse_clock_time(value: str | None, fallback: dt_time) -> dt_time:
    if not isinstance(value, str) or not value.strip():
        return fallback
    parts = value.strip().split(":", 1)
    if len(parts) != 2:
        return fallback
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        return dt_time(hour=hour, minute=minute)
    except Exception:
        return fallback


def resolve_ip_remarks_file(path: str | None = None) -> Path:
    configured = path or os.getenv("CHATMOCK_IP_REMARKS_FILE") or DEFAULT_IP_REMARKS_FILE
    return Path(configured).expanduser()


class IpRemarkRegistry:
    def __init__(self, path: str | None = None) -> None:
        self.path = resolve_ip_remarks_file(path)
        self._loaded_mtime_ns: int | None = None
        self._remarks: dict[str, str] = {}

    def _load_if_changed(self) -> None:
        try:
            stat = self.path.stat()
            mtime_ns: int | None = stat.st_mtime_ns
        except FileNotFoundError:
            mtime_ns = None

        if mtime_ns == self._loaded_mtime_ns:
            return

        if mtime_ns is None:
            self._remarks = {}
            self._loaded_mtime_ns = None
            return

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._loaded_mtime_ns = mtime_ns
            return

        if not isinstance(payload, dict):
            self._loaded_mtime_ns = mtime_ns
            return

        remarks: dict[str, str] = {}
        for raw_ip, raw_remark in payload.items():
            ip = str(raw_ip).strip()
            remark = str(raw_remark).strip()
            if ip and remark:
                remarks[ip] = remark
        self._remarks = remarks
        self._loaded_mtime_ns = mtime_ns

    def get_remark(self, remote_addr: str | None) -> str | None:
        self._load_if_changed()
        if not isinstance(remote_addr, str):
            return None
        ip = remote_addr.strip()
        if not ip:
            return None
        return self._remarks.get(ip)


def format_access_log_prefix(remote_addr: str, registry: IpRemarkRegistry) -> str:
    remark = registry.get_remark(remote_addr) or "-"
    safe_addr = remote_addr.replace("%", "%%")
    safe_remark = remark.replace("%", "%%")
    return f"{safe_addr} - {safe_remark}"


def make_access_log_handler(registry: IpRemarkRegistry) -> type[WSGIRequestHandler]:
    class ChatMockRequestHandler(WSGIRequestHandler):
        def log(self, type: str, message: str, *args: Any) -> None:
            remote_addr = self.address_string()
            prefix = format_access_log_prefix(remote_addr, registry)
            _log(
                type,
                f"{prefix} - [{self.log_date_time_string()}] {message}\n",
                *args,
            )

    return ChatMockRequestHandler


def parse_bad_gateway_window(
    start_value: str | None = None,
    end_value: str | None = None,
) -> tuple[dt_time, dt_time]:
    start = _parse_clock_time(
        start_value or os.getenv("CHATMOCK_DAILY_BAD_GATEWAY_START") or DEFAULT_BAD_GATEWAY_START,
        dt_time(hour=0, minute=0),
    )
    end = _parse_clock_time(
        end_value or os.getenv("CHATMOCK_DAILY_BAD_GATEWAY_END") or DEFAULT_BAD_GATEWAY_END,
        dt_time(hour=0, minute=30),
    )
    return start, end


def is_within_bad_gateway_window(
    start: dt_time,
    end: dt_time,
    now: datetime | None = None,
) -> bool:
    if start == end:
        return False
    current = (now or datetime.now().astimezone()).timetz().replace(tzinfo=None)
    if start < end:
        return start <= current < end
    return current >= start or current < end
