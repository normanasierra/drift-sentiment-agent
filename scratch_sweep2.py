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
def W(w): return None if w is None else getattr(w,'strike',w)
def disc(rep):
    return {b.label:(W(b.call_wall),W(b.put_wall),W(b.magneto_strike),
                     W(b.call_gamma_wall),W(b.put_gamma_wall),round(b.sigma,6) if b.sigma else None) for b in rep.buckets}
def zgs(rep): return {b.label:b.zero_gamma for b in rep.buckets}
def fmt(a,b):
    if a is None or b is None: return f"{'None':>7}"
    return f"{(a-b):+7.1f}"
tf=[c for cs in chosen.values() for c in cs]
full_rep=report_mod.build_report('SPX',spot,tf,today)
D0=disc(full_rep); Z0=zgs(full_rep)
labels=list(Z0.keys())
print(f"spot={spot:.2f}")
for frac in [0.15,0.20,0.25,0.30,0.35,0.50]:
    lo,hi=spot*(1-frac),spot*(1+frac)
    sub=[c for c in tf if lo<=c.strike<=hi]
    rep=report_mod.build_report('SPX',spot,sub,today)
    d_ok=disc(rep)==D0
    z=zgs(rep)
    per=" ".join(f"{L.split('~')[1].replace(' DTE',''):>3}:{fmt(z[L],Z0[L])}" for L in labels)
    print(f"±{int(frac*100):>3}% n={len(sub):>4} discrete_id={d_ok!s:>5}  Δzg[{per}]")
