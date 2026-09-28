from app.policy import classify, words


def test_read_needs_both_a_read_name_and_a_read_only_hint():
    assert classify("files", "read_file", {"path": "a.txt"}, {"readOnlyHint": True}).requires_approval is False
    assert classify("files", "read_file", {"path": "a.txt"}, {}).requires_approval is True


def test_server_hints_cannot_make_a_delete_safe():
    decision = classify("files", "delete_file", {"path": "a.txt"}, {"readOnlyHint": True})
    assert decision.capability == "delete"
    assert decision.requires_approval is True


def test_arguments_can_raise_risk():
    assert classify("x", "get_page", {"url": "https://evil.example"}, {"readOnlyHint": True}).capability == "network"
    assert classify("x", "helper", {"command": "rm -rf /"}, {}).capability == "execute"


def test_urls_anywhere_in_arguments_and_url_keys_mean_network():
    assert classify("x", "get_document", {"source": "see https://evil.example"}, {"readOnlyHint": True}).capability == "network"
    assert classify("x", "get_page", {"url": "evil.example"}, {"readOnlyHint": True}).capability == "network"


def test_camel_case_names_are_split():
    assert classify("x", "deleteRepo", {}, {}).capability == "delete"


def test_all_caps_runs_are_split():
    assert words("getHTTPResource") == {"get", "http", "resource"}
    assert classify("x", "getHTTPResource", {}, {"readOnlyHint": True}).capability == "network"


def test_key_and_env_tools_count_as_credentials():
    for tool_name in ("get_api_key", "read_env"):
        decision = classify("x", tool_name, {}, {"readOnlyHint": True})
        assert decision.capability == "credential"
        assert decision.requires_approval is True


def test_destructive_hint_alone_explains_itself():
    decision = classify("files", "write_file", {"path": "a.txt"}, {"destructiveHint": True})
    assert decision.capability == "delete"
    assert decision.reason == "Server marks this destructive (it may overwrite or delete data)."


def test_unknown_tools_require_approval():
    assert classify("x", "frobnicate", {}, {}).requires_approval is True


def test_user_can_trust_a_specific_read_tool(monkeypatch):
    monkeypatch.setenv("MCP_CONTROL_TRUSTED_READ_TOOLS", "files:directory_tree")
    assert classify("files", "directory_tree", {"path": "."}, {}).requires_approval is False
    assert classify("other", "directory_tree", {"path": "."}, {}).requires_approval is True
