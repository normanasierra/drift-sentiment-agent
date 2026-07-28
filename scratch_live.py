import time, datetime, statistics
from drift_sentiment import polygon_client as pc, report as report_mod, chain_filter
today = datetime.date.today()
TARGETS = sorted({dte for _, dte in chain_filter.DTE_TARGETS}, reverse=True)

def W(w): return None if w is None else getattr(w,'strike',w)
def show(rep):
    for b in rep.buckets:
        print(f"  {b.label:>16}: call_wall={W(b.call_wall)} put_wall={W(b.put_wall)} "
              f"magneto={W(b.magneto_strike)} zeroΓ={b.zero_gamma:.2f} "
              f"callGW={W(b.call_gamma_wall)} putGW={W(b.put_gamma_wall)}")

# time NEW banded targeted, 3 runs
ts=[]
for i in range(3):
    t0=time.time(); spot,cs=pc.fetch_chain_targeted('SPX',today,TARGETS); t1=time.time()
    ts.append(t1-t0)
    print(f"run{i}: fetch_chain_targeted SPX(banded) {t1-t0:.2f}s  spot={spot} n={len(cs)}")
print(f"NEW banded median: {statistics.median(ts):.2f}s")
rep=report_mod.build_report('SPX',spot,cs,today)
print("NEW banded report levels:")
show(rep)
