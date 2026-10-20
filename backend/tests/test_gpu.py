"""The GPU shared by the agent's model and the renders: one side at a time, the other's models put out first."""

import asyncio

import pytest

from scene import gpu


def test_the_same_machine_is_told_by_its_address():
    assert gpu.same_machine("http://100.123.221.34:11434", "http://100.123.221.34:8188")
    assert gpu.same_machine("http://localhost:11434", "http://127.0.0.1:8188")
    assert not gpu.same_machine("http://localhost:11434", "http://100.123.221.34:8188")
    assert not gpu.same_machine("", "http://100.123.221.34:8188")


def gate(log, shared=True):
    async def free_for(side):
        log.append("free for " + side)
    return gpu.Gate(lambda: shared, free={"llm": lambda: free_for("llm"), "render": lambda: free_for("render")})


def test_a_render_waits_for_the_agent_and_the_model_is_put_out_first():
    log = []

    async def go():
        g = gate(log)

        async def think():
            async with g.use("llm"):
                log.append("thinking")
                await asyncio.sleep(0.2)
                async with g.use("llm"):   # its own calls inside the message do not take it again
                    log.append("a call")
                log.append("thought")

        async def render():
            await asyncio.sleep(0.05)
            async with g.use("render", waiting=lambda: log.append("waiting")):
                log.append("rendering")
        await asyncio.gather(think(), render())
        return g.busy()
    busy = asyncio.run(go())
    assert log == ["free for llm", "thinking", "waiting", "a call", "thought", "free for render", "rendering"]
    assert busy == {"side": None, "users": 0, "waiting": {"llm": 0, "render": 0}}


def test_a_side_waiting_keeps_newer_calls_of_the_other_side_out():
    log = []

    async def go():
        g = gate(log)

        async def first():
            async with g.use("llm"):
                await asyncio.sleep(0.2)
                log.append("first done")

        async def render():
            await asyncio.sleep(0.05)
            async with g.use("render"):
                log.append("rendering")
                await asyncio.sleep(0.1)

        async def second():
            await asyncio.sleep(0.1)   # comes while the render waits: it goes after the render
            async with g.use("llm"):
                log.append("second")
        await asyncio.gather(first(), render(), second())
    asyncio.run(go())
    assert [e for e in log if not e.startswith("free")] == ["first done", "rendering", "second"]
    assert log.count("free for llm") == 2 and log.count("free for render") == 1


def test_a_cancelled_job_stops_waiting():
    log, stop = [], []

    async def go():
        g = gate(log)

        async def think():
            async with g.use("llm"):
                await asyncio.sleep(1.5)

        async def render():
            await asyncio.sleep(0.05)
            stop.append(True)
            with pytest.raises(gpu.Stopped):
                async with g.use("render", stop=lambda: bool(stop)):
                    log.append("rendered")
            log.append("stopped")
        await asyncio.gather(think(), render())
    asyncio.run(go())
    assert "rendered" not in log and "stopped" in log


def test_nothing_waits_when_the_gpu_is_not_shared():
    log = []

    async def go():
        g = gate(log, shared=False)
        async with g.use("llm"):
            async with g.use("render"):
                log.append("both")
    asyncio.run(go())
    assert log == ["both"]


def test_a_polite_call_waits_for_the_renders_queued_and_keeps_no_one_out():
    log, queued = [], [2]   # two renders wait to start

    async def go():
        g = gpu.Gate(lambda: True, pending={"render": lambda: queued[0] > 0})

        async def check():
            with gpu.politely():
                async with g.use("llm"):
                    log.append("checked")

        async def renders():
            await asyncio.sleep(0.05)
            for n in range(2):
                async with g.use("render"):
                    queued[0] -= 1
                    log.append("render %d" % n)
                    await asyncio.sleep(0.1)
        await asyncio.gather(check(), renders())
    asyncio.run(go())
    assert log == ["render 0", "render 1", "checked"]
