import datetime
from drift_sentiment import polygon_client as pc, report as report_mod, chain_filter
from drift_sentiment.polygon_client import _monthly_candidates
today = datetime.date.today()
TARGETS = sorted({dte for _, dte in chain_filter.DTE_TARGETS}, reverse=True)
spot, contracts = pc.fetch_chain('SPX')
by_exp={}
for c in contracts: by_exp.setdefault(c.expiration,[]).append(c)
chosen={}
for target in TARGETS:
    for cand in _monthly_candidates(today,target):
        if cand in chosen: break
        if cand in by_exp: chosen[cand]=by_exp[cand]; break
tf=[c for cs in chosen.values() for c in cs]
strikes=sorted({c.strike for c in tf})
print(f"spot={spot} strike range=[{min(strikes)},{max(strikes)}] n_strikes={len(strikes)} contracts={len(tf)}")

def zg(cts):
    rep=report_mod.build_report('SPX',spot,cts,today)
    return {b.label:(b.zero_gamma,b.total_gex) for b in rep.buckets}

full=zg(tf)
print("\nband   nContr  " + "  ".join(f"{L.split('~')[1]:>9}" for L in full))
for frac in [0.30,0.35,0.40,0.45,0.50,0.60,0.70,1.00]:
    lo,hi=spot*(1-frac),spot*(1+frac)
    sub=[c for c in tf if lo<=c.strike<=hi]
    d=zg(sub)
    diffs=[]
    for L in full:
        zf=full[L][0]; zb=d[L][0]
        diffs.append(f"{(zb-zf):+9.2f}" if zf and zb else "     None")
    print(f"±{int(frac*100):>3}%  {len(sub):>5}   " + "  ".join(diffs))
print("\n(values = banded zero_gamma - full zero_gamma, in index points)")
