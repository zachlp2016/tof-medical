"""Exercise the official SDK client against a real HTTP server, not mocks."""
import asyncio
import hashlib
import socket
import threading
import time
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from app.config import Settings
from app.main import create_app


def test_official_client_over_real_http():
    token = "network-test-only-token"
    settings = Settings(database_url="sqlite:///:memory:", demo_mode=True,
                        principals={hashlib.sha256(token.encode()).hexdigest(): {"tenant_id": "demo-clinic", "actor_id": "sdk-test", "scopes": ["ehr:read"]}})
    server_socket = socket.socket()
    server_socket.bind(("127.0.0.1", 0))
    port = server_socket.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [server_socket]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started

    async def run():
        async with streamablehttp_client(f"http://127.0.0.1:{port}/mcp", headers={"Authorization": f"Bearer {token}"}) as (read, write, _):
            async with ClientSession(read, write) as session:
                result = await session.initialize()
                assert result.protocolVersion == "2025-11-25"
                listing = await session.list_tools()
                assert len(listing.tools) == 5
                result = await session.call_tool("get_patient_chart", {"patient_id": "demo-patient-1"})
                assert not result.isError
                assert "Eleanor Pena" in str(result.content)
    try:
        asyncio.run(run())
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        server_socket.close()
    assert not thread.is_alive()
