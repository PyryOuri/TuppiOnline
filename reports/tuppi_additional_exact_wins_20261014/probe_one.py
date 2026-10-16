"""Bounded fresh-process oracles and synthetic fixed-deal cost probes."""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time

OUT = Path(__file__).resolve().parent
PREP = OUT.parent / 'tuppi_cheap_wins_preparation_20261014'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['roots', 'mlp', 'compact_mlp', 'game'], required=True)
    parser.add_argument('--variant', required=True)
    parser.add_argument('--worlds', type=int, default=128)
    parser.add_argument('--samples', type=int, default=2)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    signal.alarm(90)
    start, cpu = time.perf_counter(), time.process_time()
    sys.path.insert(0, str(PREP))
    from bootstrap import activate
    activate()
    import numpy as np
    import torch
    torch.set_num_threads(1)
    import candidates
    from tuppi_ai import native, best
    original_configure, original_agents = candidates.configure_native, candidates.agents

    def configure(arm, serial=True):
        original_configure('reward_bucket' if args.variant == 'combined_speed' else 'baseline', serial=serial)
        if args.variant == 'chunk128': native.set_rollout_chunk(128)

    candidates.configure_native = configure
    if args.variant in ('combined_speed', 'same_net_only', 'compact_rows'):
        candidates.agents = lambda arm, **kw: original_agents('same_net', **kw)
    configure('baseline', serial=True)
    if args.mode == 'roots':
        from native_roots import roots
        records = []
        for index, obs, ids, worlds, setting in roots(native):
            actor = candidates.agents('baseline', worlds=worlds, seed=index+1, seats=[obs.seat])[obs.seat]
            sr = actor.searcher
            if setting: sr.env.set_sooli(17, False, setting == 1, 0.3)
            begin = time.perf_counter()
            values = sr.action_values(obs, ids)
            records.append({'index':index, 'worlds':worlds, 'contract':int(obs.contract), 'phase':int(obs.phase),
                'played':int(obs.n_played), 'mode':setting, 'ids':ids, 'values':[float(v).hex() for v in values],
                'rng':sr.rng.value, 'observation_hash':hashlib.sha256(bytes(obs)).hexdigest(), 'wall_seconds':time.perf_counter()-begin})
        result = {'schema':'tuppi.cheap_wins.native_roots.v1', 'rows':records}
    elif args.mode in ('mlp', 'compact_mlp'):
        from concurrent.futures import ThreadPoolExecutor
        from native_roots import roots
        observations = [obs for _, obs, *_ in roots(native)]
        result = {'schema': 'tuppi.additional_exact_wins.mlp.v1', 'hashes': [], 'blanked_neighbour_mismatches': 0,
                  'thread_mismatches': 0, 'clear_mismatches': 0, 'compacted_row_mismatches': 0}
        for path in (best.OPPONENT_ROLLOUT, best.ANCHOR):
            net = candidates.loaded(str(path)); mlp = native.Mlp(net)
            seed = np.random.default_rng(571)
            visible = np.stack([native.encode(o, encoder=net.encoder) for o in observations])
            for rows in (1, 3, 4, 8, 16, 31, 32, 33, 64, 128, 256):
                features = visible[np.arange(rows) % len(visible)].copy()
                if rows > 4:
                    features[2] = 0
                    features[3] = (seed.random(features.shape[1]) < 0.04).astype(np.uint8)
                baseline = mlp.forward(features)
                mask = np.arange(rows) % 3 == 1
                blanked = features.copy(); blanked[mask] = 0
                alternate = mlp.forward(blanked)
                result['blanked_neighbour_mismatches'] += int(np.count_nonzero(baseline[~mask].view(np.uint32) != alternate[~mask].view(np.uint32)))
                if args.mode == 'compact_mlp':
                    compact = mlp.forward(features[~mask].copy())
                    result['compacted_row_mismatches'] += int(np.count_nonzero(baseline[~mask].view(np.uint32) != compact.view(np.uint32)))
                result['hashes'].append({'model':path.name, 'rows':rows, 'sha256':hashlib.sha256(baseline.tobytes()).hexdigest()})
                with ThreadPoolExecutor(max_workers=2) as executor:
                    outputs = list(executor.map(lambda _: mlp.forward(features), range(6)))
                result['thread_mismatches'] += sum(int(np.count_nonzero(baseline.view(np.uint32) != output.view(np.uint32))) for output in outputs)
                clear = getattr(native.lib, 'tc_probe_scratch_clear', None)
                if clear:
                    clear.argtypes = []; clear.restype = None; clear()
                    output = mlp.forward(features)
                    result['clear_mismatches'] += int(np.count_nonzero(baseline.view(np.uint32) != output.view(np.uint32)))
        assert result['blanked_neighbour_mismatches'] == result['thread_mismatches'] == result['clear_mismatches'] == 0
    else:
        import worker
        job = {'id':args.variant, 'kind':'full_deals', 'arm':'baseline', 'worlds':args.worlds,
               'samples':args.samples, 'seed':'cw-w1024-qualification-v1', 'scores':'uniform', 'serial':True,
               'cpu_seconds':60, 'wall_seconds':90}
        context = {'scope':'additional_pre_strength_validation', 'base_package_sha256':hashlib.sha256((PREP/'PACKAGE.json').read_bytes()).hexdigest(),
                   'controller_lifecycle':'retained', 'rollout_chunk':128 if args.variant=='chunk128' else 32,
                   'native_parallel':False, 'workers':1, 'design':'full_deals'}
        result = worker.full_deals(job, context)
        result.update(candidate=args.variant, job=job)
    result.update(variant=args.variant, wall_seconds=time.perf_counter()-start, cpu_seconds=time.process_time()-cpu,
                  library=str(native._LIB_PATH), library_sha256=hashlib.sha256(native._LIB_PATH.read_bytes()).hexdigest(),
                  dependency_versions={'torch':torch.__version__,'numpy':np.__version__,'python':sys.version,'executable':sys.executable})
    for name, field in [('tc_probe_rollout_metric','rollout_metrics'),('tc_probe_mlp_metric','mlp_metrics')]:
        function = getattr(native.lib,name,None)
        if function:
            function.argtypes=[C.c_int]; function.restype=C.c_uint64
            result[field] = [function(i) for i in range(3)]
    with args.out.open('x') as f: json.dump(result,f,indent=2,allow_nan=False)
    print(json.dumps({'variant':args.variant,'mode':args.mode,'cpu_seconds':result['cpu_seconds']}),flush=True)
    signal.alarm(0)


if __name__ == '__main__': main()
