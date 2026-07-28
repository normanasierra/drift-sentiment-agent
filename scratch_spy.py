import math, datetime
from drift_sentiment import polygon_client as pc, report as report_mod, chain_filter
from drift_sentiment.polygon_client import _monthly_candidates, _band_frac
today = datetime.date.today()
TARGETS = sorted({dte for _, dte in chain_filter.DTE_TARGETS}, reverse=True)
spot, contracts = pc.fetch_chain('SPY')
by_exp={}
for c in contracts: by_exp.setdefault(c.expiration,[]).append(c)
chosen={}
for target in TARGETS:
    for cand in _monthly_candidates(today,target):
        if cand in chosen: break
        if cand in by_exp: chosen[cand]=by_exp[cand]; break
def W(w): return None if w is None else getattr(w,'strike',w)
def lv(rep): return {b.label:(W(b.call_wall),W(b.put_wall),W(b.magneto_strike)) for b in rep.buckets}
tf=[c for cs in chosen.values() for c in cs]
banded=[]
for cand,cs in chosen.items():
    f=_band_frac((cand-today).days); lo,hi=spot*(1-f),spot*(1+f)
    banded+=[c for c in cs if lo<=c.strike<=hi]
full=report_mod.build_report('SPY',spot,tf,today); band=report_mod.build_report('SPY',spot,banded,today)
LF,LB=lv(full),lv(band)
print(f"SPY spot={spot} (SINGLE snapshot, deterministic)")
print("discrete identical:", LF==LB)
for L in LF:
    tag="" if LF[L]==LB[L] else "  <-- CHANGED"
    print(f"  {L:>16}: full(cw,pw,mag)={LF[L]}  band={LB[L]}{tag}")
# show top put OI strikes for the 90 DTE bucket
for cand,cs in chosen.items():
    dte=(cand-today).days
    if 70<dte<100:
        puts=sorted([c for c in cs if c.contract_type=='put'], key=lambda c:-c.open_interest)[:5]
        print(f"\n  {cand} ({dte}DTE) top put OI strikes:", [(p.strike,p.open_interest) for p in puts], f" band_low={spot*(1-_band_frac(dte)):.0f}")
