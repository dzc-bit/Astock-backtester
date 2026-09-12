from __future__ import annotations

import pytest
from astock_backtester.ai.sessions import SessionStore


def test_create_get_save_roundtrip(tmp_path):
    store = SessionStore(tmp_path)
    session = store.create(title="测试会话")
    assert session["messages"] == [] and session["display"] == []

    session["messages"].append({"role": "user", "content": "你好"})
    session["display"].append({"role": "user", "content": "你好"})
    store.save(session)

    loaded = store.get(session["session_id"])
    assert loaded is not None
    assert loaded["title"] == "测试会话"
    assert loaded["messages"][0]["content"] == "你好"


def test_list_and_delete(tmp_path):
    store = SessionStore(tmp_path)
    first = store.create("第一条")
    second = store.create("第二条")
    assert {item["title"] for item in store.list_sessions()} == {"第一条", "第二条"}
    assert store.delete(first["session_id"]) is True
    assert store.get(first["session_id"]) is None
    assert [item["session_id"] for item in store.list_sessions()] == [second["session_id"]]


def test_unsafe_session_id_rejected(tmp_path):
    store = SessionStore(tmp_path)
    assert store.get("../../etc/passwd") is None
    assert store.delete("bad/id") is False
    # 斜杠等非法字符被清洗而不是穿透路径
    session = {"session_id": "bad/id", "display": [], "messages": []}
    store.save(session)
    assert (tmp_path / "AI对话" / "badid.json").exists()
    # 清洗后为空则拒绝
    with pytest.raises(ValueError):
        store.save({"session_id": "///", "display": [], "messages": []})


def test_persisted_messages_capped(tmp_path):
    store = SessionStore(tmp_path)
    session = store.create()
    for index in range(500):
        session["messages"].append({"role": "user", "content": str(index)})
        session["display"].append({"role": "user", "content": str(index)})
    store.save(session)
    loaded = store.get(session["session_id"])
    assert len(loaded["messages"]) == 400
    assert len(loaded["display"]) == 400
