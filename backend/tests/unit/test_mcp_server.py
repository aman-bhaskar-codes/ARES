from __future__ import annotations

import json

from ares.mcp_server import process_message


def test_mcp_server_protocol_lifecycle() -> None:
    # 1. Initialize
    init_msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "req-1",
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )
    init_resp = json.loads(process_message(init_msg) or "{}")
    assert init_resp["id"] == "req-1"
    assert init_resp["result"]["serverInfo"]["name"] == "ares-research-server"
    assert "tools" in init_resp["result"]["capabilities"]

    # 2. List tools
    list_msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "req-2",
            "method": "tools/list",
            "params": {},
        }
    )
    list_resp = json.loads(process_message(list_msg) or "{}")
    tool_names = [t["name"] for t in list_resp["result"]["tools"]]
    assert "ares_search_evidence" in tool_names
    assert "ares_query_memory" in tool_names
    assert "ares_get_status" in tool_names

    # 3. Call tool
    call_msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "req-3",
            "method": "tools/call",
            "params": {
                "name": "ares_get_status",
                "arguments": {},
            },
        }
    )
    call_resp = json.loads(process_message(call_msg) or "{}")
    content_text = call_resp["result"]["content"][0]["text"]
    assert "ARES Autonomous Research Engine" in content_text

    # 4. Unknown tool error
    err_msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "req-4",
            "method": "tools/call",
            "params": {
                "name": "non_existent_tool",
                "arguments": {},
            },
        }
    )
    err_resp = json.loads(process_message(err_msg) or "{}")
    assert "error" in err_resp
    assert err_resp["error"]["code"] == -32601
