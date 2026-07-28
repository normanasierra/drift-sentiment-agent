import time, datetime, statistics
import drift_sentiment.polygon_client as pc
from drift_sentiment import report as report_mod, chain_filter
today = datetime.date.today()
TARGETS = sorted({dte for _, dte in chain_filter.DTE_TARGETS}, reverse=True)
def W(w): return None if w is None else getattr(w,'strike',w)

# --- A: UNFILTERED (simulate OLD) by forcing band off ---
_real = pc._fetch_spot
def timeit(label, patch):
    ts=[]
    for i in range(3):
        t0=time.time(); spot,cs=pc.fetch_chain_targeted('SPX',today,TARGETS); t1=time.time()
        ts.append(t1-t0)
    return statistics.median(ts), spot, cs

# OLD: disable band by making _band_frac huge (>= max cap forces full-ish) — better: patch center resolution off
orig_bf = pc._band_frac
pc._band_frac = lambda dte: 999.0  # band = ±99900% => effectively full chain
mo, spotO, csO = timeit("OLD", None)
pc._band_frac = orig_bf
mn, spotN, csN = timeit("NEW", None)

print(f"OLD (unfiltered) median: {mo:.2f}s  n={len(csO)}")
print(f"NEW (DTE-band)   median: {mn:.2f}s  n={len(csN)}")
print(f"speedup: {mo/mn:.2f}x   contracts {len(csO)}->{len(csN)} ({100*len(csN)/len(csO):.0f}%)")

repO=report_mod.build_report('SPX',spotO,csO,today)
repN=report_mod.build_report('SPX',spotN,csN,today)
def lv(rep): return {b.label:(W(b.call_wall),W(b.put_wall),W(b.magneto_strike),W(b.call_gamma_wall),W(b.put_gamma_wall)) for b in rep.buckets}
LO,LN=lv(repO),lv(repN)
print("\nDiscrete levels OLD vs NEW (walls/magneto/gammaWalls):", "IDENTICAL" if LO==LN else "DIFFER")
for L in LO:
    zo=[b.zero_gamma for b in repO.buckets if b.label==L][0]
    zn=[b.zero_gamma for b in repN.buckets if b.label==L][0]
    print(f"  {L:>16}: {LO[L]}  zeroΓ old={zo:.2f} new={zn:.2f} Δ={zn-zo:+.2f}")
