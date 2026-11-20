import asyncio
import time

from starrocks_mcp import server
from starrocks_mcp.config import Settings


def test_database_tools_do_not_block_event_loop(monkeypatch):
    monkeypatch.setattr(server, "SETTINGS", Settings())

    def slow_list(_settings):
        time.sleep(0.5)
        return ["demo"]

    monkeypatch.setattr(server, "_list_databases", slow_list)

    async def run_two_calls():
        started = time.perf_counter()
        results = await asyncio.gather(
            server.list_databases(),
            server.list_databases(),
        )
        return results, time.perf_counter() - started

    results, elapsed = asyncio.run(run_two_calls())
    assert results == [["demo"], ["demo"]]
    assert elapsed < 0.9
