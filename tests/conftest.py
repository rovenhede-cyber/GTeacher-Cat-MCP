import json
import os
import sys
import tempfile

import pytest

# 测试日志写到临时文件，避免改动仓库内的 logs/gteacher_cat.log
os.environ.setdefault(
    "GTEACHER_LOG", os.path.join(tempfile.gettempdir(), "gteacher_cat_test.log")
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "instructions.json")


@pytest.fixture(scope="session")
def library_data():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def offline_library(library_data):
    """所有用例默认离线：把 fixture 注入引擎缓存，绝不触网。"""
    import sticker_engine

    sticker_engine.set_library(library_data)
    return library_data


@pytest.fixture()
def library(library_data):
    """把 fixture 注入引擎缓存，测试不触网。"""
    import sticker_engine

    sticker_engine.set_library(library_data)
    yield library_data


@pytest.fixture()
def by_id(library):
    return {item["id"]: item for item in library["stickers"]}
