import autopsy


def item(i, v=100):
    return {"id": i, "value": v}


def make_run(workers, final, key=("A", "B", "C", "D"), universe=None, baseline_final=(),
             baseline_status="ok"):
    universe = universe or ["A", "B", "C", "D", "E", "F", "G", "H"]
    return {
        "run_id": "r", "config": {"model": "m", "temperature": 0, "workers": len(workers)},
        "task": {"task_id": "t", "size": "S", "seed": 1, "n_lines": len(universe)},
        "items": {"universe": universe, "key": [item(k) for k in key]},
        "swarm": {
            "planner": {"status": "ok", "briefs_used": len(workers), "parse_notes": []},
            "workers": [{"worker": n + 1, "brief": "b", "ranges": [], "slice": list(sl),
                         "reported": [item(i) for i in rep], "status": "ok", "parse_notes": []}
                        for n, (sl, rep) in enumerate(workers)],
            "merger": {"status": "ok", "final": [item(i) for i in final]},
        },
        "baseline": {"status": baseline_status, "call": {},
                     "final": None if baseline_final is None else [item(i) for i in baseline_final]},
    }


def test_each_bucket():
    # A: never assigned. B: assigned, missed. C: dropped at merge. D: kept.
    run = make_run([(["B", "C", "E"], ["C"]), (["D", "F"], ["D"])], final=["D"])
    a = autopsy.swarm_autopsy(run)
    by = {p["id"]: p["bucket"] for p in a["per_item"]}
    assert by == {"A": "never_assigned", "B": "assigned_missed",
                  "C": "dropped_at_merge", "D": "kept"}
    assert a["lost"] == 3 and sum(a["buckets"].values()) == 4
    assert a["score"]["recall"] == 0.25 and a["score"]["precision"] == 1.0


def test_bucket_priority_kept_beats_everything():
    run = make_run([(["A"], ["A"]), (["A"], [])], final=["A"], key=("A",))
    assert autopsy.swarm_autopsy(run)["per_item"][0]["bucket"] == "kept"


def test_one_worker_reports_other_misses_is_dropped_not_missed():
    run = make_run([(["A"], ["A"]), (["A"], [])], final=[], key=("A",))
    assert autopsy.swarm_autopsy(run)["per_item"][0]["bucket"] == "dropped_at_merge"


def test_false_positive_split():
    # E: real line reported by worker and kept. ZZ: nonexistent id invented by merger.
    # F: worker false positive the merger filtered out.
    run = make_run([(["A", "E", "F"], ["A", "E", "F"])], final=["A", "E", "ZZ"])
    fp = autopsy.swarm_autopsy(run)["false_positives"]
    assert fp["worker_reported_kept"] == [{"id": "E", "kind": "real_line"}]
    assert fp["invented_by_merger"] == [{"id": "ZZ", "kind": "nonexistent_id"}]
    assert fp["worker_fps_filtered_by_merger"] == 1


def test_duplicates_and_coverage():
    run = make_run([(["A", "B", "E"], []), (["B", "E", "F"], [])], final=[])
    cov = autopsy.swarm_autopsy(run)["coverage"]
    assert cov["lines_in_2plus_slices"] == 2 and cov["key_lines_in_2plus_slices"] == 1
    assert cov["lines_unassigned"] == 4  # C, D, G, H


def test_empty_final_precision_undefined():
    s = autopsy.swarm_autopsy(make_run([(["A"], [])], final=[]))["score"]
    assert s["precision"] is None and s["recall"] == 0


def test_repeated_ids_in_final_deduped():
    run = make_run([(["A"], ["A"])], final=["A", "a", "A "])
    s = autopsy.swarm_autopsy(run)["score"]
    assert s["final_count"] == 1 and s["duplicates_in_final"] == 2


def test_value_accuracy_tolerance():
    run = make_run([(["A", "B"], ["A", "B"])], final=[])
    run["swarm"]["merger"]["final"] = [{"id": "A", "value": 101}, {"id": "B", "value": 150}]
    acc = autopsy.swarm_autopsy(run)["score"]["value_accuracy"]
    assert acc == {"accurate": 1, "found": 2, "rate": 0.5}


def test_planner_failure_all_never_assigned_and_flagged():
    run = make_run([], final=[])
    run["swarm"]["planner"]["status"] = "unparseable"
    run["swarm"]["merger"]["status"] = "not_called"
    a = autopsy.swarm_autopsy(run)
    assert a["buckets"]["never_assigned"] == 4
    assert any("planner unparseable" in f for f in a["flags"])


def test_baseline_did_not_fit_is_not_scored():
    run = make_run([(["A"], ["A"])], final=["A"], baseline_final=None,
                   baseline_status="rejected_too_large")
    run["baseline"]["call"] = {"requested_tokens": 14000, "limit_tokens": 7000}
    b = autopsy.baseline_autopsy(run)
    assert "score" not in b and b["requested_tokens"] == 14000


def test_baseline_scored():
    b = autopsy.baseline_autopsy(make_run([], final=[], baseline_final=["A", "B", "E"]))
    assert b["score"]["recall"] == 0.5 and b["missed"] == 2


def test_render_runs():
    run = make_run([(["B", "C", "E"], ["C"]), (["D", "F"], ["D"])], final=["D"])
    text = autopsy.render(run)
    assert "never assigned (split)" in text and "Every lost key item" in text
