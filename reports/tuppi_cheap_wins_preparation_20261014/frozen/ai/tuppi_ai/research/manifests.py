"""Disabled pilot manifests instantiated from the package template (C1.03 and later).

Nothing here enables or launches an experiment. A manifest is written with
`execution_enabled: false`, `approval: null` and null resource caps; the
proposed sizes and rules are planning proposals for the owner to approve,
change or reject. `cli validate-manifest` reports NOT_LAUNCHABLE until a
completed, approved copy exists.
"""

from __future__ import annotations

import json
from pathlib import Path

from .identity import OUTPUT_DIR, PLAN_DIR, sha256_file

RESEARCH_FILES = ("identity.py", "records.py", "observation.py", "lifecycle.py", "native_api.py", "clone_policy.py",
                  "streams.py", "fixtures.py", "runner_v3.py", "statistics.py", "c1_control_variate.py",
                  "c1_dispatch.py", "c3_utility_stop.py", "c3_kernel.py", "c2_blind_bids.py", "ledger.py",
                  "probe.py", "parity.py", "cli.py", "manifests.py", "testing.py")


def _template(mechanism: str) -> dict:
    t = json.loads((PLAN_DIR / "PILOT_MANIFEST_TEMPLATE.json").read_text())
    return dict(next(x for x in t["templates"] if x["mechanism"] == mechanism))


def source_hashes() -> dict:
    from .identity import AI_ROOT

    out = {f"tuppi_ai/research/{f}": sha256_file(AI_ROOT / "tuppi_ai" / "research" / f) for f in RESEARCH_FILES}
    for f in ("overlay.patch", "research_api.c", "research_api.h", "build_research.sh", "pinned_sources.sha256"):
        out[f"native/research/{f}"] = sha256_file(AI_ROOT / "native" / "research" / f)
    for f in ("tuppi_ai/best.py", "tuppi_ai/search.py", "tuppi_ai/native.py", "tuppi_ai/bridge.py"):
        out[f] = sha256_file(AI_ROOT / f)
    return out


def build_ids() -> dict:
    from .native_api import INSTALLED_DYLIB, RESEARCH_LIB, SOURCE_LIB

    return {"B0-installed": sha256_file(INSTALLED_DYLIB), "B0-source": sha256_file(SOURCE_LIB),
            "R0-parity": sha256_file(RESEARCH_LIB),
            "note": "B0-source is byte-identical to B0-installed (builds/build_manifest.txt)"}


def c1_manifest() -> dict:
    from .c1_control_variate import ESTIMATOR_VERSION, PROXY_VERSION

    calib = json.loads((OUTPUT_DIR / "logs" / "c1_cost_calibration.json").read_text())
    m = _template("C1")
    m.update({
        "manifest_id": "c1-pilot-proposal-v1",
        "execution_enabled": False,
        "approval": None,
        "candidate_id": {"primary": "C1-shadow-v1 (beta frozen on FIT; M, n frozen on PLAN)",
                         "separate_variant": "C1-natural-v1 (own-stream advancement; a different complete policy)"},
        "baseline_id": "B0-source best_agents(worlds=128) dd_left=6 search_showing=1, seed map seed+2*seat",
        "native_build_ids": build_ids(),
        "source_hashes": source_hashes(),
        "lifecycle_contract": {
            "mechanism_endpoint": "decision-case replay: every case evaluated from a fresh cold agent fork "
                                  "(ReplayFork/NativeFork); no controller state carried between cases",
            "case_harvest": "independent_cold_bundle v3 deals, B0-source best agents at every seat"},
        "policy_factories_by_seat": {str(s): "best(worlds=128, seed=bundle seat seed)" for s in range(4)},
        "opponent_population": "the same frozen W128 family at every other seat (case harvesting)",
        "score_distribution": {"law": "zero", "weights": {"0-0": 1.0},
                               "note": "one declared law; legacy 'uniform' is not uniform over 25 states"},
        "estimator_version": {"estimator": ESTIMATOR_VERSION, "proxy": PROXY_VERSION,
                              "reference_action": "clone preferred legal discard, engine tie order",
                              "beta": "single scalar: slope from fit_beta_on_split (FIT only; within-case/action "
                                      "centred, equal case weights), frozen as optimal_beta(slope, M, n) once M, n "
                                      "are fixed on PLAN",
                              "allocation": "min over integer n of max_a(A_a/M + B_a/n) at the W128 baseline's "
                                            "measured CPU, from PLAN data only"},
        "splits": {
            "FIT": {"parent_namespace": "c1-fit-v1", "proposed_base_deals": 64},
            "PLAN": {"parent_namespace": "c1-plan-v1", "proposed_base_deals": 128},
            "SCREEN": {"parent_namespace": "c1-screen-v1", "proposed_base_deals": 256},
            "CONFIRM": {"parent_namespace": "c1-confirm-v1", "proposed_base_deals": None,
                        "rule": "sized from PLAN variance after a candidate is nominated; opened once"},
            "split_key": "original_parent_deal_id", "parent_overlap_allowed": False},
        "required_sample_size": None,
        "sample_size_basis": "PLAN paired-cluster SD of the MSE-difference endpoint -> statistics.power_n; "
                             "not historical SDs",
        "variance_estimate": None,
        "cpu_seconds_cap": None, "wall_seconds_cap": None, "memory_bytes_cap": None,
        "max_workers": None, "max_native_concurrency": None,
        "proposed_resource_shape": {"max_workers": 1, "max_native_concurrency": 1,
                                    "note": "native search already uses every core; nested concurrency untested"},
        "per_decision_deadline_ms": None,
        "one_final_look": True,
        "multiplicity_plan": "one nominated candidate (shadow); the natural variant is reported descriptively",
        "futility_rule": None,
        "proposed_futility_rule": "stop C1 after PLAN if the upper 95% bound of the reference-noise-corrected "
                                  "MSE ratio at equal CPU is >= 0.9 (proposal; needs approval)",
        "independent_reference_plan": {"worlds": 2048, "replicates": 2, "stream_namespace": "reference",
                                       "rule": "all legal actions on fresh explicit worlds, independent of the "
                                               "candidate, baseline and selection streams"},
        "reference_noise_adjustment": "statistics.mse_endpoints: corrected ratio and MSE difference",
        "seed_namespace": {"cases": "deal|c1-<split>-v1|<index>",
                           "cheap": "cheap|<run>|seat|<seat>|pre-call-rng|<agent scalar RNG before the call>",
                           "expensive": "expensive|<run>|seat|<seat>|pre-call-rng|<agent scalar RNG before the call>",
                           "reference": "reference|<run>|<case>", "validation": "validation|<run>|<case>",
                           "agents": "per-bundle seat seeds (runner_v3.bundle_seed); cases forked from them"},
        "stream_protocol": "shadow advancement: candidate streams hash a copy of the agent's pre-call scalar RNG "
                           "state (actor-local, distinct per agent and call, reproduced by forks); the persistent "
                           "RNG is then advanced by W root draws exactly as W128 (V09)",
        "checkpoint_frequency": "per base deal",
        "result_path": "research_runs/<run_id>/c1_results.json",
        "equity_noninferiority_margin": -0.0005,
        "secondary_endpoints": ["recommendation disagreement with W128", "paired selected-value difference on "
                                "fresh common validation worlds", "estimator variance", "branch frequency and "
                                "CPU fraction f", "CPU/wall including sampling, shadow, proxy and reference"],
        "contract_calibration": calib,
        "planning_constraint": ("Measured on fixtures: a W128 NOLO discard costs 0.03-0.3 s CPU while a bid search "
                                "costs 2-6 s (builds/parity_B0-source.json). The discard branch is therefore likely "
                                "a small CPU fraction f, and the total saving is bounded by f*r "
                                "(statistics.total_saving_bound). Measure f first; if f < 0.2 the full-game "
                                "'20% total CPU' promotion route is arithmetically unreachable for C1 and only the "
                                "local MSE endpoint or a separately powered strength test remains."),
        "do_not_launch_reason": "Disabled: no owner approval and no numeric CPU/wall/memory caps; CONFIRM size "
                                "unset; futility rule is only proposed",
    })
    return m


def write(name: str, manifest: dict) -> Path:
    path = OUTPUT_DIR / "research" / name
    path.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return path


if __name__ == "__main__" and "--all" not in __import__("sys").argv:
    from .cli import validate_manifest

    p = write("c1_pilot_manifest.json", c1_manifest())
    print(json.dumps(validate_manifest(p), indent=1))


def mechanism_manifest(mechanism: str, **fields) -> dict:
    """A disabled manifest for one later mechanism: template + identities + contract findings."""
    m = _template(mechanism)
    m.update({"execution_enabled": False, "approval": None, "native_build_ids": build_ids(),
              "source_hashes": source_hashes(), **fields})
    return m


LATER = {
    "C3b": dict(manifest_id="c3b-pilot-proposal-v1", candidate_id="R0 + RESEARCH_OPT_UTILITY_STOP (C3b certificate v1)",
                baseline_id="R0-parity with switches off (== B0-source on the probe set)",
                estimator_version="c3b.superset_t0_to_t0_plus_r.float32_equity_delta.v1",
                primary_endpoint_note="identical float target on every row (bitwise per_world) and saved work/CPU",
                contract_findings="On F02b at 0-48 with a 2-trick tail 146/256 rows certified with bitwise-equal "
                                  "values; with the as-is 6-trick tail 0 rows certified on the tested case. Measure "
                                  "the natural eligible-row rate first: the as-is gain may be small.",
                do_not_launch_reason="Disabled: no approval or caps"),
    "C2": dict(manifest_id="c2-pilot-proposal-v1",
               candidate_id="C2-RC (event weighting + actual chosen cards), clone predecessors; search-fork variant C2.02",
               baseline_id="current forced-prefix reconstruction (F) inside W128 bid search",
               estimator_version="c2.joint_layouts.F_R_RC.v1",
               contract_findings="On F01 the clone predecessors passed in 23/23 sampled layouts: R ~ F there. "
                                 "Reach frequencies by seat/score are the first pilot quantity.",
               do_not_launch_reason="Disabled: no approval or caps; searching-predecessor calibration not run"),
    "C3a": dict(manifest_id="c3a-pilot-proposal-v1", candidate_id="C3-marginal-RNG-mode-model-v1 (reduced C==P: 1600 states)",
                baseline_id="direct complete v3 match pairs with fresh B0 agents",
                estimator_version="c3a.sparse_kernel.bundle_bootstrap.v1",
                contract_findings="Kernel solver reproduces the equity table on the 100-state chain; C==P tested on "
                                  "one bid search. The model is an idealisation, not B0.",
                do_not_launch_reason="Disabled: state model not validated against direct matches; no approval or caps"),
    "C4": dict(manifest_id="c4-pilot-proposal-v1", candidate_id="legal 52-card giver/receiver scorers (untrained)",
               baseline_id="frozen W128 searched give + heuristic return, frozen offer and play",
               estimator_version="c4.giver_weighted_joint_objective.v1",
               contract_findings="Payoff tables with frozen heuristic play controllers; exact toys show uniform "
                                 "message weighting fails. Convention-aware defence UNRESOLVED.",
               do_not_launch_reason="Disabled: training and fresh accepted-offer bank require approval"),
    "C5": dict(manifest_id="c5-pilot-proposal-v1",
               candidate_id="c5.three_card_option.fixed_native_clone_others.uniform_complete_support.v1",
               baseline_id="W128 at every remaining root decision (forked state)",
               estimator_version="c5.information_group_option.v1",
               contract_findings="F05: 18-world complete support, 1017 nodes, 21 ms; option >= W128 comparator in "
                                 "the fixed-clone model.",
               do_not_launch_reason="Disabled: no approval or caps; transfer to searching opponents unmeasured"),
}

if __name__ == "__main__" and "--all" in __import__("sys").argv:
    from .cli import validate_manifest

    for mech, fields in LATER.items():
        p = write(f"{mech.lower()}_pilot_manifest.json", mechanism_manifest(mech, **fields))
        print(mech, validate_manifest(p)["verdict"])
