"""Exercise authorization before requests can reach the writable runtime."""
import http.client
import json
import threading

import pytest

from agentcad.errors import AgentCADError
from agentcad.http_api import MAX_BODY, make_server
from agentcad.policy import Policy

TOKEN = "test-only-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@pytest.fixture
def server(ws):
    srv = make_server(Policy(root=ws), port=0, token=TOKEN)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def request(srv, *, method="POST", path="/v1/create_drawing", body=b'{"path":"x.dxf"}', headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=10)
    base = {"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN}
    base.update(headers or {})
    try:
        conn.request(method, path, body=None if method == "GET" else body, headers=base)
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


@pytest.mark.parametrize("headers,status,code", [
    ({"Authorization": "Bearer wrong"}, 401, "UNAUTHORIZED"),
    ({"Host": "attacker.example"}, 403, "HOST_NOT_ALLOWED"),
    ({"Host": "127.0.0.1@attacker.example"}, 403, "HOST_NOT_ALLOWED"),
    ({"Host": "127.0.0.1:invalid"}, 403, "HOST_NOT_ALLOWED"),
    ({"Origin": "https://attacker.example"}, 403, "ORIGIN_NOT_ALLOWED"),
    ({"Origin": "null"}, 403, "ORIGIN_NOT_ALLOWED"),
    ({"Content-Type": "text/plain"}, 415, "CONTENT_TYPE_REQUIRED"),
    ({"Content-Length": "-1"}, 400, "INVALID_BODY_LENGTH"),
    ({"Content-Length": "bad"}, 400, "INVALID_BODY_LENGTH"),
    ({"Content-Length": str(MAX_BODY + 1)}, 413, "BODY_TOO_LARGE"),
    ({"Transfer-Encoding": "chunked"}, 400, "INVALID_BODY_LENGTH"),
])
def test_http_refuses_before_writing(server, ws, headers, status, code):
    actual, result = request(server, headers=headers)
    assert actual == status and result["error"]["code"] == code
    assert not (ws / "x.dxf").exists()
    # A rejected request cannot poison the next valid operation.
    actual, result = request(server)
    assert actual == 200 and result["ok"] and (ws / "x.dxf").exists()


def test_tool_catalog_requires_authentication_too(server):
    status, result = request(server, method="GET", path="/v1/tools", headers={"Authorization": ""})
    assert status == 401 and result["error"]["code"] == "UNAUTHORIZED"
    status, result = request(server, method="GET", path="/v1/tools")
    assert status == 200 and "apply_operations" in result["tools"]


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.5", "::", "cad.example"])
def test_remote_bind_is_refused_before_opening_socket(ws, host):
    with pytest.raises(AgentCADError, match="Non-loopback") as error:
        make_server(Policy(root=ws), host, 0)
    assert error.value.code == "HTTP_AUTH_REQUIRED"


@pytest.mark.parametrize("token", ["", "short", " " * 32, "é" * 32, "x" * 31 + "\x00"])
def test_invalid_token_cannot_start_server(ws, token):
    with pytest.raises(AgentCADError) as error:
        make_server(Policy(root=ws), port=0, token=token)
    assert error.value.code == "HTTP_TOKEN_INVALID"


def test_remote_bind_with_token_still_authenticates(ws):
    srv = make_server(Policy(root=ws), "0.0.0.0", 0, token=TOKEN)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        status, _ = request(srv, headers={"Host": "cad.example", "Authorization": ""})
        assert status == 401 and not (ws / "x.dxf").exists()
        status, result = request(srv, headers={"Host": "cad.example"})
        assert status == 200 and result["ok"]
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_malformed_json_and_arguments_are_recoverable(server, ws):
    for body in (b"{broken", b"[]", b'"text"'):
        status, result = request(server, body=body)
        assert status == 400 and result["error"]["code"] == "INVALID_JSON"
    status, result = request(server, body=b'{"unknown":1}')
    assert status == 400 and result["error"]["code"] == "INVALID_ARGUMENTS"
    assert not (ws / "x.dxf").exists()


def test_early_refusals_keep_their_response_when_body_arrives(server, ws):
    # Exercise header/body delivery races on Windows, including the size branch.
    for _ in range(15):
        status, result = request(server, headers={"Content-Length": str(MAX_BODY + 1)})
        assert status == 413 and result["error"]["code"] == "BODY_TOO_LARGE"
        status, result = request(server, path="/v1/missing")
        assert status == 404 and result["error"]["code"] == "UNKNOWN_TOOL"
    assert not (ws / "x.dxf").exists()
