import math, datetime, time
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
tf=[c for cs in chosen.values() for c in cs]
full=report_mod.build_report('SPX',spot,tf,today); D0=disc(full); Z0=zgs(full)

for k in [0.040, 0.045, 0.050]:
    def bf(d): return min(0.70, max(0.22, k*math.sqrt(d)))
    banded=[]; rows=[]
    for cand,cs in chosen.items():
        dte=(cand-today).days; f=bf(dte); lo,hi=spot*(1-f),spot*(1+f)
        keep=[c for c in cs if lo<=c.strike<=hi]; banded+=keep
        rows.append(f"{dte}d±{f*100:.0f}%:{len(cs)}->{len(keep)}")
    rep=report_mod.build_report('SPX',spot,banded,today)
    zdel=[]
    for L in Z0:
        a,b=Z0[L],zgs(rep)[L]
        zdel.append("None" if (a is None or b is None) else f"{b-a:+.1f}")
    print(f"k={k}: TOTAL {len(tf)}->{len(banded)} ({100*len(banded)/len(tf):.0f}%) disc_id={disc(rep)==D0}  Δzg={zdel}  [{'  '.join(rows)}]")
