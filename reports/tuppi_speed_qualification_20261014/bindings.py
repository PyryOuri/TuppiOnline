"""Common exact-speed factory for later baseline/hard-anchor/ensemble comparisons."""
import ctypes as C
import hashlib
import os
from pathlib import Path
import sys

OUT=Path(__file__).resolve().parent
PREP=OUT.parent/'tuppi_cheap_wins_preparation_20261014'
VARIANTS={'reference':('installed',False,32),'combo32':('reward',True,32),
          'combo128':('reward',True,128),'compact128':('reward_compact',True,128)}


def activate(variant, parallel=False):
    if variant not in VARIANTS: raise ValueError('Unknown speed variant')
    library,shared,chunk=VARIANTS[variant]
    path=PREP/'frozen/ai/native/libtuppi.dylib' if library=='installed' else OUT/'builds'/library/'libtuppi.dylib'
    os.environ['TUPPI_CHEAP_WINS_LIBRARY']=str(path)
    sys.path.insert(0,str(PREP))
    from bootstrap import activate as choose_snapshot
    choose_snapshot()
    import torch
    torch.set_num_threads(1)
    import candidates
    from tuppi_ai import native,best
    candidates.configure_native('baseline' if variant=='reference' else 'reward_bucket',serial=not parallel)
    native.set_rollout_chunk(chunk)
    return candidates,native,best


def agents(candidates,native,best,variant,worlds,seed=0,seats=range(4),arm='baseline'):
    if arm not in {'baseline','hard_anchor','suit_ensemble'}: raise ValueError('Unsupported strength arm')
    if variant=='reference': return candidates.agents(arm,worlds=worlds,seed=seed,seats=seats)
    if worlds<1 or worlds>4096 or worlds>128 and worlds%128: raise ValueError('Unsupported world cap')
    net=candidates.loaded(str(best.OPPONENT_ROLLOUT)); team=candidates.loaded(str(best.TEAM_ROLLOUT))
    if net is not team: raise ValueError('Shared-model qualification requires identical frozen models')
    anchor=candidates.loaded(str(best.ANCHOR)); shared=native.Mlp(net)
    anchor_mlp=native.Mlp(anchor) if arm=='suit_ensemble' else None
    result={}
    for seat in seats:
        actor=candidates.AnalysisAgent(net,candidates.equity().table,seat,worlds=worlds,dd_left=best.SOLVER_TAIL,
            search_showing=1,seed=seed+seat,adaptive=best.ADAPTIVE_BIDS if worlds>128 else None,
            team_net=None,shared_mlp=shared,keep=best.KEEP,blueprint_net=anchor,rami_bonus=-best.RAMI_MARGIN,keep_show=best.KEEP_SHOW)
        actor.arm,actor.anchor_mlp=arm,anchor_mlp
        result[seat]=actor
    return result


def track_sooli(actor):
    # Captured C environment starts calloc-zeroed; its options are assigned
    # only by this setter. Track writes rather than relying on private offsets.
    for sr in (actor.searcher,actor.show_searcher):
        if sr is None: continue
        env=sr.env; old=env.set_sooli
        env.qualification_sooli=[0,False,False,0.]
        def tracked(belief=0,return_pi=False,play_heur=False,lam=0.3,*,_env=env,_old=old):
            _old(belief,return_pi,play_heur,lam)
            _env.qualification_sooli=[int(belief),bool(return_pi),bool(play_heur),float(lam)]
        env.set_sooli=tracked
