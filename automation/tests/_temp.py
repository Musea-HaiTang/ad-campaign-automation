# -*- coding: utf-8 -*-
"""测试临时目录：固定放在仓库 _tmp 内，兼容 WorkBuddy 沙箱。"""
from contextlib import contextmanager
from pathlib import Path
import shutil
import uuid


TEMP_ROOT = Path(__file__).resolve().parents[1] / "_tmp" / "test-data"


def make_temp_workdir(prefix: str = "test-") -> str:
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEMP_ROOT / f"{prefix}{uuid.uuid4().hex}"
    path.mkdir()
    return str(path)


@contextmanager
def temp_workdir(prefix: str = "test-"):
    path = Path(make_temp_workdir(prefix))
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)
