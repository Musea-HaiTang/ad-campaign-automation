# -*- coding: utf-8 -*-
"""执行层远端事实与本地请求指纹的统一口径。

管什么：远端对象是确认存在、确认不存在还是无法确认；同一业务键的请求内容
是否发生变化。
不管什么：怎么查某个后台页面、怎么点击、怎么建对象。
谁什么时候读：执行层写模式和断点对账时；各 run_*.py 的页面查询只负责产出
`RemoteState`，恢复策略统一交给 bucket_runner。
"""
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping

FOUND = "found"
ABSENT = "absent"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class RemoteState:
    kind: str
    object_id: str = ""
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_found(self):
        return self.kind == FOUND

    @property
    def is_absent(self):
        return self.kind == ABSENT

    @property
    def is_unknown(self):
        return self.kind == UNKNOWN


def found(object_id="", reason="", **metadata):
    return RemoteState(FOUND, str(object_id or ""), reason, metadata)


def absent(reason=""):
    return RemoteState(ABSENT, reason=reason)


def unknown(reason=""):
    return RemoteState(UNKNOWN, reason=reason)


def normalize(value):
    """兼容旧的 True/False/None 查询结果；无法判断时按 UNKNOWN 处理。"""
    if isinstance(value, RemoteState):
        return value
    if value is True:
        return found()
    if value is False:
        return absent()
    if value is None:
        return unknown()
    raise TypeError("远端状态必须是 RemoteState / True / False / None，实际是 %r" % (value,))


def payload_hash(payload):
    """对业务载荷做稳定指纹；字典键顺序不影响结果。"""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
