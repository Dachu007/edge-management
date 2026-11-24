"""
AI-Augmented Edge Resource Management for Smart Cities - Web Application
Run:  python app.py      then open  http://127.0.0.1:5000
"""
import csv
import io
import os
import random
import threading
from collections import deque

from flask import Flask, jsonify, render_template, request, Response

from edge.models import TASK_PROFILES, PRIORITY_LABEL
from edge.allocator import EdgeResourceManager, QLearningAgent, POLICY_LABELS, FIXED_MAP
from edge.simulation import generate_arrivals, make_task, compare_policies, train_agent
from edge.testcases import run_all

BASE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE, "models", "q_table.json")

app = Flask(__name__)
LOCK = threading.Lock()


# --------------------------------------------------------------------- agent
def load_or_train_agent():
    if os.path.exists(MODEL_PATH):
        try:
            return QLearningAgent.load(MODEL_PATH), []
        except Exception:
            pass
    print("Training Q-learning agent (first run, ~5 s)...")
    agent, curve = train_agent(episodes=40)
    agent.save(MODEL_PATH)
    return agent, curve


AGENT, TRAIN_CURVE = load_or_train_agent()


# ------------------------------------------------------------- live system
class LiveSystem:
    """A continuously running city simulation shown on the dashboard."""

    def __init__(self):
        self.policy = "ai"
        self.learning_enabled = True
        self.energy_weight = 0.2
        self.burst = False
        self.rate_scale = 1.0
        self.reset()

    def reset(self):
        self.mgr = EdgeResourceManager(policy=self.policy, agent=AGENT,
                                       learning_enabled=self.learning_enabled,
                                       energy_weight=self.energy_weight, seed=42,
                                       keep_records=3000, keep_history=0)
        self.clock = 0.0
        self.rng = random.Random(42)
        self.next_id = 1
        self.series = deque(maxlen=60)
        self.mgr.monitor.collect(0.0)

    def apply_config(self):
        self.mgr.policy = self.policy
        self.mgr.learning_enabled = self.learning_enabled
        self.mgr.energy_weight = self.energy_weight

    def tick(self, step_ms=1000.0):
        arrivals = generate_arrivals(self.clock, self.clock + step_ms, self.rng,
                                     burst=self.burst, rate_scale=self.rate_scale)
        for t, ttype in arrivals:
            task = make_task(self.next_id, ttype, round(t, 2), self.rng)
            self.next_id += 1
            self.mgr.allocate(task)
        self.clock += step_ms
        snaps = self.mgr.monitor.collect(self.clock)
        self.series.append({
            "t": round(self.clock / 1000, 1),
            "cpu": {k: (round(v.cpu_util * 100, 1) if v.cpu_util is not None else None) for k, v in snaps.items()},
            "power": {k: v.power_w for k, v in snaps.items()},
            "arrivals": len(arrivals),
        })
        return len(arrivals)

    def submit(self, ttype, overrides):
        task = make_task(self.next_id, ttype, self.clock, self.rng, **overrides)
        self.next_id += 1
        return self.mgr.allocate(task, with_trace=True)

    def state(self):
        snaps = self.mgr.monitor.collect(self.clock)
        nodes = []
        for n in self.mgr.nodes:
            s = snaps[n.node_id].to_dict()
            s.update(n.info())
            s["overloaded"] = self.mgr.balancer.is_overloaded(n.node_id, self.clock)
            s["tasks_assigned"] = n.assigned
            nodes.append(s)
        summary = self.mgr.reporter.summary(self.mgr.nodes, horizon_ms=max(self.clock, 1.0))
        return {
            "clock_s": round(self.clock / 1000, 1),
            "config": {"policy": self.policy, "learning_enabled": self.learning_enabled,
                       "energy_weight": self.energy_weight, "burst": self.burst,
                       "rate_scale": self.rate_scale},
            "nodes": nodes,
            "summary": summary,
            "series": list(self.series),
            "recent": list(self.mgr.reporter.records)[-25:][::-1],
            "events": list(self.mgr.reporter.events)[-15:][::-1],
        }


LIVE = LiveSystem()
LAST_SIM = {"managers": {}}


# ------------------------------------------------------------------ routes
@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/meta")
def meta():
    return jsonify({
        "task_profiles": TASK_PROFILES,
        "priority_labels": PRIORITY_LABEL,
        "policies": POLICY_LABELS,
        "fixed_map": FIXED_MAP,
        "nodes": [n.info() for n in LIVE.mgr.nodes],
        "agent": {"states": len(AGENT.q), "episodes": AGENT.episodes_trained},
        "train_curve": TRAIN_CURVE,
    })


@app.get("/api/state")
def state():
    with LOCK:
        return jsonify(LIVE.state())


@app.post("/api/tick")
def tick():
    steps = int((request.get_json(silent=True) or {}).get("steps", 1))
    with LOCK:
        for _ in range(max(1, min(steps, 30))):
            LIVE.tick()
        return jsonify(LIVE.state())


@app.post("/api/task")
def submit_task():
    d = request.get_json(force=True)
    ttype = d.get("task_type", "traffic")
    if ttype not in TASK_PROFILES:
        return jsonify({"error": "unknown task type"}), 400

    def num(k):
        v = d.get(k)
        return float(v) if v not in (None, "") else None

    overrides = {"work_mi": num("work_mi"), "memory_gb": num("memory_gb"),
                 "data_mb": num("data_mb"), "deadline_ms": num("deadline_ms"),
                 "priority": int(d["priority"]) if d.get("priority") not in (None, "") else None}
    with LOCK:
        rec = LIVE.submit(ttype, overrides)
        return jsonify({"decision": rec, "state": LIVE.state()})


@app.post("/api/node/<node_id>")
def node_update(node_id):
    d = request.get_json(force=True)
    with LOCK:
        node = LIVE.mgr.node_map.get(node_id)
        if node is None:
            return jsonify({"error": "unknown node"}), 404
        if "online" in d:
            node.online = bool(d["online"])
            LIVE.mgr.reporter.event(LIVE.clock, "admin", f"{node_id} set {'online' if node.online else 'offline (stops reporting)'}")
        if "report_missing" in d:
            node.report_missing = bool(d["report_missing"])
            LIVE.mgr.reporter.event(LIVE.clock, "admin", f"{node_id} missing-values mode = {node.report_missing}")
        return jsonify(LIVE.state())


@app.post("/api/config")
def config():
    d = request.get_json(force=True)
    with LOCK:
        if d.get("policy") in POLICY_LABELS:
            LIVE.policy = d["policy"]
        if "learning_enabled" in d:
            LIVE.learning_enabled = bool(d["learning_enabled"])
        if "energy_weight" in d:
            LIVE.energy_weight = float(d["energy_weight"])
            AGENT.energy_weight = LIVE.energy_weight
        if "burst" in d:
            LIVE.burst = bool(d["burst"])
        if "rate_scale" in d:
            LIVE.rate_scale = max(0.1, min(4.0, float(d["rate_scale"])))
        LIVE.apply_config()
        LIVE.mgr.reporter.event(LIVE.clock, "admin",
                                f"Config: policy={LIVE.policy}, learning={LIVE.learning_enabled}, "
                                f"burst={LIVE.burst}, load x{LIVE.rate_scale}")
        return jsonify(LIVE.state())


@app.post("/api/reset")
def reset():
    with LOCK:
        LIVE.reset()
        return jsonify(LIVE.state())


@app.post("/api/simulate")
def simulate():
    d = request.get_json(force=True)
    policies = [p for p in d.get("policies", list(POLICY_LABELS)) if p in POLICY_LABELS] or list(POLICY_LABELS)
    duration = max(10, min(int(d.get("duration_s", 60)), 300))
    with LOCK:
        result, managers = compare_policies(
            policies, duration_s=duration, seed=int(d.get("seed", 1)),
            burst=bool(d.get("burst", True)), rate_scale=float(d.get("rate_scale", 1.0)),
            energy_weight=float(d.get("energy_weight", 0.2)), agent=AGENT)
        LAST_SIM["managers"] = managers
    return jsonify(result)


@app.get("/api/report.csv")
def report_csv():
    policy = request.args.get("policy", "ai")
    mgr = LAST_SIM["managers"].get(policy)
    if mgr is None:
        return Response("Run a simulation first.", status=404)
    buf = io.StringIO()
    cols = ["task_id", "task_type", "priority", "arrival_ms", "node_id", "deferred", "reason",
            "net_ms", "wait_ms", "exec_ms", "completion_ms", "deadline_ms", "met", "energy_j",
            "decision_us", "policy_used", "fallback"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in mgr.reporter.records:
        w.writerow(r)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=decision_log_{policy}.csv"})


@app.post("/api/train")
def train():
    global AGENT, TRAIN_CURVE
    d = request.get_json(silent=True) or {}
    episodes = max(5, min(int(d.get("episodes", 40)), 200))
    with LOCK:
        agent, curve = train_agent(episodes=episodes, energy_weight=float(d.get("energy_weight", 0.2)))
        agent.save(MODEL_PATH)
        AGENT, TRAIN_CURVE = agent, curve
        LIVE.mgr.agent = AGENT
    return jsonify({"curve": curve, "states": len(AGENT.q), "episodes": AGENT.episodes_trained})


@app.get("/api/tests")
def tests():
    return jsonify(run_all(AGENT))


if __name__ == "__main__":
    print("\n  Open http://127.0.0.1:5000 in your browser\n")
    app.run(debug=True, use_reloader=False)
