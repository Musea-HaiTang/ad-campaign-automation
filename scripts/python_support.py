# -*- coding: utf-8 -*-
"""项目支持的 Python 版本范围。"""

MIN_PYTHON_MINOR = 11
MAX_PYTHON_MINOR = 15
SUPPORTED_PYTHON_LABEL = "Python 3.11-3.15"


def supported_python(major: int, minor: int) -> bool:
    return major == 3 and MIN_PYTHON_MINOR <= minor <= MAX_PYTHON_MINOR
