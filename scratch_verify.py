import time, datetime
from drift_sentiment import polygon_client as pc, report as report_mod, chain_filter
from drift_sentiment.polygon_client import _monthly_candidates, STRIKE_BAND_FRAC
today = datetime.date.today()
TARGETS = sorted({dte for _, dte in chain_filter.DTE_TARGETS}, reverse=True)

# --- one live full snapshot; everything else derived in-memory (no drift) ---
spot, contracts = pc.fetch_chain('SPX')
by_exp = {}
for c in contracts:
    by_exp.setdefault(c.expiration, []).append(c)

# Reproduce what fetch_chain_targeted picks: first listed monthly per target.
chosen = {}
for target in TARGETS:
    for cand in _monthly_candidates(today, target):
        if cand in chosen: break
        if cand in by_exp:
            chosen[cand] = by_exp[cand]; break

targeted_full = [c for cs in chosen.values() for c in cs]
lo, hi = spot*(1-STRIKE_BAND_FRAC), spot*(1+STRIKE_BAND_FRAC)
targeted_band = [c for c in targeted_full if lo <= c.strike <= hi]
print(f"spot={spot}  band=[{lo:.1f},{hi:.1f}]")
print(f"targeted expirations: {sorted(str(e) for e in chosen)}")
print(f"contracts: targeted_full={len(targeted_full)}  targeted_band={len(targeted_band)}  (full chain={len(contracts)})")

def W(w):
    if w is None: return None
    return getattr(w,'strike',w)
def levels(rep):
    out={}
    for b in rep.buckets:
        out[b.label]=(W(b.call_wall),W(b.put_wall),W(b.magneto_strike),
                      b.zero_gamma, W(b.call_gamma_wall), W(b.put_gamma_wall),
                      b.total_gex, b.sigma, b.magneto_notional)
    return out

rep_a = report_mod.build_report('SPX', spot, targeted_full, today)  # same-spot unfiltered
rep_b = report_mod.build_report('SPX', spot, targeted_band, today)  # same-spot banded
A, B = levels(rep_a), levels(rep_b)

ok = True
for k in A:
    if A[k] != B[k]:
        ok = False
        print(f"DIFF {k}:\n  full={A[k]}\n  band={B[k]}")
print("\nRESULT: banded == unfiltered (same spot)?", "IDENTICAL ✓" if ok else "DIFFERENT ✗")
for k,v in A.items():
    print(f"  {k}: call_wall={v[0]} put_wall={v[1]} magneto={v[2]} zeroG={v[3]:.4f} callGW={v[4]} putGW={v[5]}")
