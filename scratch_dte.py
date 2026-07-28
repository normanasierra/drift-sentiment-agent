import math, datetime
from drift_sentiment import polygon_client as pc, report as report_mod, chain_filter
from drift_sentiment.polygon_client import _monthly_candidates
today = datetime.date.today()
TARGETS = sorted({dte for _, dte in chain_filter.DTE_TARGETS}, reverse=True)
spot, contracts = pc.fetch_chain('SPX')
by_exp={}
for c in contracts: by_exp.setdefault(c.expiration,[]).append(c)
chosen={}; target_of={}
for target in TARGETS:
    for cand in _monthly_candidates(today,target):
        if cand in chosen: break
        if cand in by_exp:
            chosen[cand]=by_exp[cand]; target_of[cand]=target; break

def band_frac(dte):
    # ~3σ of a σ√T gamma spread: keeps each bucket's Zero-Γ flip within live jitter.
    return min(0.70, max(0.25, 0.11*math.sqrt(dte)))

def W(w): return None if w is None else getattr(w,'strike',w)
def disc(rep):
    return {b.label:(W(b.call_wall),W(b.put_wall),W(b.magneto_strike),
                     W(b.call_gamma_wall),W(b.put_gamma_wall),round(b.sigma,6) if b.sigma else None) for b in rep.buckets}
def zgs(rep): return {b.label:b.zero_gamma for b in rep.buckets}

tf=[c for cs in chosen.values() for c in cs]
full=report_mod.build_report('SPX',spot,tf,today); D0=disc(full); Z0=zgs(full)

# apply per-target band
banded=[]
for cand,cs in chosen.items():
    dte=(cand-today).days
    f=band_frac(dte); lo,hi=spot*(1-f),spot*(1+f)
    keep=[c for c in cs if lo<=c.strike<=hi]
    banded+=keep
    print(f"exp {cand} dte={dte:>3} band=±{f*100:4.1f}%  {len(cs):>4} -> {len(keep):>4}")
print(f"TOTAL {len(tf)} -> {len(banded)}  ({100*len(banded)/len(tf):.0f}%)")
rep=report_mod.build_report('SPX',spot,banded,today)
D1=disc(rep); Z1=zgs(rep)
print("discrete identical:", D1==D0)
for L in Z0:
    a,b=Z0[L],Z1[L]
    print(f"  {L:>16} zero_gamma full={a} banded={b} Δ={None if (a is None or b is None) else round(b-a,2)}")
