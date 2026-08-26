"""pytest 全局配置

- 设置占位 API key，避免 import app.main 时 LLM 工厂校验崩溃
- 提供临时目录 fixture
"""

import os
import tempfile
from pathlib import Path

import pytest


def pytest_configure(config):
    """测试启动前注入占位环境变量，避免缺 API key 导致 import 失败"""
    for key in (
        "SILICONFLOW_API_KEY",
        "DASHSCOPE_API_KEY",
        "OPENAI_API_KEY",
    ):
        os.environ.setdefault(key, "test-placeholder")


@pytest.fixture
def tmp_db_path():
    """返回一个临时 SQLite 文件路径，测试结束后清理"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = tmp.name
    yield path
    Path(path).unlink(missing_ok=True)
