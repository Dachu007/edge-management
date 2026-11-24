"""
Core data model for the AI-Augmented Edge Resource Manager.

Entities follow the ER diagram in the report (Fig 4.1):
    Application -> Task Request -> Allocation Decision -> Edge Node
    Edge Node   -> Resource Snapshot
    Allocation Decision -> Performance Record

Units used everywhere:
    time      : milliseconds (ms)
    work      : million instructions (MI)
    speed     : MIPS per core
    memory    : GB
    data size : MB
    bandwidth : Mbps
    power     : W,   energy : J (reported as Wh)

Energy is a MODEL-BASED ESTIMATE (linear idle-to-max power model),
not a hardware measurement - as required in Section 1.3 of the report.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional, List

# --------------------------------------------------------------------------
# Smart-city workload profiles (Section 1.1: traffic, surveillance,
# emergency and environmental sensing have different processing needs)
# --------------------------------------------------------------------------
TASK_PROFILES = {
    "traffic": {
        "label": "Traffic analytics", "work": (300, 600), "mem": (0.5, 1.0),
        "data": (0.5, 2.0), "min_bw": 10, "priority": 2, "deadline": 600, "rate": 10.0,
    },
    "surveillance": {
        "label": "Surveillance video", "work": (1500, 3000), "mem": (1.0, 2.0),
        "data": (8.0, 20.0), "min_bw": 50, "priority": 1, "deadline": 2500, "rate": 3.0,
    },
    "emergency": {
        "label": "Emergency monitoring", "work": (100, 200), "mem": (0.2, 0.5),
        "data": (0.2, 1.0), "min_bw": 5, "priority": 3, "deadline": 250, "rate": 1.0,
    },
    "environment": {
        "label": "Environmental sensing", "work": (20, 60), "mem": (0.05, 0.1),
        "data": (0.01, 0.05), "min_bw": 1, "priority": 1, "deadline": 2000, "rate": 15.0,
    },
}

PRIORITY_LABEL = {1: "Low", 2: "Medium", 3: "High"}

# --------------------------------------------------------------------------
# Simulated edge infrastructure (capacities deliberately unequal, Sec 1.1)
# --------------------------------------------------------------------------
NODE_CONFIG = [
    dict(node_id="N1", name="Junction Edge",        cores=4,  mips=2000, memory_gb=8,  bandwidth_mbps=100,  latency_ms=5,  idle_w=60,  max_w=150, jitter=0.15),
    dict(node_id="N2", name="Transit Hub Edge",     cores=8,  mips=2500, memory_gb=16, bandwidth_mbps=200,  latency_ms=10, idle_w=90,  max_w=250, jitter=0.10),
    dict(node_id="N3", name="Hospital Zone Edge",   cores=4,  mips=1500, memory_gb=8,  bandwidth_mbps=80,   latency_ms=8,  idle_w=50,  max_w=120, jitter=0.15),
    dict(node_id="N4", name="Residential Edge",     cores=2,  mips=1200, memory_gb=4,  bandwidth_mbps=50,   latency_ms=15, idle_w=30,  max_w=70,  jitter=0.45),
    dict(node_id="N5", name="City Micro Data Centre", cores=16, mips=3000, memory_gb=64, bandwidth_mbps=1000, latency_ms=35, idle_w=200, max_w=500, jitter=0.10),
]


@dataclass
class Task:
    task_id: int
    task_type: str
    work_mi: float
    memory_gb: float
    data_mb: float
    min_bw_mbps: float
    priority: int
    deadline_ms: float
    arrival_ms: float

    def to_dict(self):
        d = asdict(self)
        d["label"] = TASK_PROFILES.get(self.task_type, {}).get("label", self.task_type)
        d["priority_label"] = PRIORITY_LABEL.get(self.priority, str(self.priority))
        return d


@dataclass
class ResourceSnapshot:
    node_id: str
    timestamp: float
    cpu_util: Optional[float]
    mem_used_gb: Optional[float]
    mem_free_gb: Optional[float]
    bandwidth_mbps: Optional[float]
    queue_len: Optional[int]
    est_wait_ms: Optional[float]
    latency_ms: Optional[float]
    power_w: Optional[float]
    status: str = "ok"            # ok | stale | missing | unavailable
    age_ms: float = 0.0
    issues: List[str] = field(default_factory=list)

    REQUIRED = ("cpu_util", "mem_used_gb", "mem_free_gb", "bandwidth_mbps",
                "queue_len", "est_wait_ms", "latency_ms", "power_w")

    def missing_fields(self):
        return [f for f in self.REQUIRED if getattr(self, f) is None]

    def to_dict(self):
        return asdict(self)


@dataclass
class Estimate:
    core: int
    net_ms: float          # propagation latency + data transfer
    wait_ms: float         # queueing delay at the node
    exec_ms: float         # processing time
    completion_ms: float   # arrival -> finish
    start_ms: float
    finish_ms: float
    energy_j: float        # dynamic energy for this task (estimate)


class EdgeNode:
    """A simulated edge server with multiple cores and FIFO per-core queues."""

    def __init__(self, node_id, name, cores, mips, memory_gb, bandwidth_mbps,
                 latency_ms, idle_w, max_w, jitter=0.1):
        self.node_id = node_id
        self.name = name
        self.cores = cores
        self.mips = mips
        self.memory_gb = memory_gb
        self.bandwidth_mbps = bandwidth_mbps
        self.latency_ms = latency_ms
        self.idle_w = idle_w
        self.max_w = max_w
        self.jitter = jitter          # run-time variability (unknown to the planner)
        self.online = True            # False -> node stops reporting (TC02)
        self.report_missing = False   # True -> snapshot has missing values (TC03)
        self.reset()

    # ---------------------------------------------------------------- state
    def reset(self):
        self.core_free = [0.0] * self.cores
        self.jobs = []                # (arrival, start, finish, mem_gb)
        self.busy_ms = 0.0
        self.task_energy_j = 0.0
        self.assigned = 0

    def _prune(self, t):
        if self.jobs:
            self.jobs = [j for j in self.jobs if j[2] > t]

    def cpu_util(self, t):
        self._prune(t)
        running = sum(1 for j in self.jobs if j[1] <= t < j[2])
        return min(1.0, running / self.cores)

    def queue_len(self, t):
        self._prune(t)
        return sum(1 for j in self.jobs if j[1] > t)

    def mem_used(self, t):
        self._prune(t)
        return sum(j[3] for j in self.jobs)

    def est_wait(self, t):
        return max(0.0, min(self.core_free) - t)

    def power(self, t):
        return self.idle_w + (self.max_w - self.idle_w) * self.cpu_util(t)

    @property
    def joules_per_mi(self):
        return (self.max_w - self.idle_w) / self.cores / self.mips

    # ------------------------------------------------------------ planning
    def estimate(self, task: Task, t: float) -> Estimate:
        net = self.latency_ms + task.data_mb * 8.0 / self.bandwidth_mbps * 1000.0
        ready = t + net
        core = min(range(self.cores), key=lambda i: self.core_free[i])
        start = max(ready, self.core_free[core])
        exec_ms = task.work_mi / self.mips * 1000.0
        finish = start + exec_ms
        energy = (self.max_w - self.idle_w) / self.cores * exec_ms / 1000.0
        return Estimate(core, net, start - ready, exec_ms, finish - t, start, finish, energy)

    # ------------------------------------------------------------ execution
    def assign(self, task: Task, t: float, rng) -> Estimate:
        """Execute the task. Actual times include random slow-downs (jitter)."""
        slow = 1.0 + rng.uniform(-self.jitter / 3, self.jitter)
        net_slow = 1.0 + rng.uniform(0, self.jitter)
        net = (self.latency_ms + task.data_mb * 8.0 / self.bandwidth_mbps * 1000.0) * net_slow
        ready = t + net
        core = min(range(self.cores), key=lambda i: self.core_free[i])
        start = max(ready, self.core_free[core])
        exec_ms = task.work_mi / self.mips * 1000.0 * slow
        finish = start + exec_ms
        energy = (self.max_w - self.idle_w) / self.cores * exec_ms / 1000.0
        self.core_free[core] = finish
        self.jobs.append((t, start, finish, task.memory_gb))
        self.busy_ms += exec_ms
        self.task_energy_j += energy
        self.assigned += 1
        return Estimate(core, net, start - ready, exec_ms, finish - t, start, finish, energy)

    def info(self):
        return dict(node_id=self.node_id, name=self.name, cores=self.cores, mips=self.mips,
                    memory_gb=self.memory_gb, bandwidth_mbps=self.bandwidth_mbps,
                    latency_ms=self.latency_ms, idle_w=self.idle_w, max_w=self.max_w,
                    online=self.online, report_missing=self.report_missing)


def build_nodes():
    return [EdgeNode(**cfg) for cfg in NODE_CONFIG]
