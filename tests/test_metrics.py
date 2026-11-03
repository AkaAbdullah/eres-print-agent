from eres_print_agent.metrics import UsageSampler, memory_mb
from eres_print_agent.models import AgentHeartbeat, AgentUsage


def test_memory_is_read():
    value = memory_mb()
    assert value is not None and 5 < value < 2000


def test_cpu_percent_tracks_work():
    sampler = UsageSampler()
    sum(i * i for i in range(2_000_000))  # burn some CPU
    cpu, memory = sampler.sample()
    assert cpu is not None and cpu > 1
    assert memory is not None


def test_heartbeat_carries_usage():
    message = AgentHeartbeat(queueDepth=0, usage=AgentUsage(cpuPercent=0.3, memoryMb=45.2))
    assert '"usage":{"cpuPercent":0.3,"memoryMb":45.2}' in message.model_dump_json()
