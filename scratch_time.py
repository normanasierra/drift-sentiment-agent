import time, datetime
from drift_sentiment import polygon_client as pc, chain_filter
from drift_sentiment.polygon_client import _monthly_candidates, _fetch_expiration, _api_key, _fetch_spot
today = datetime.date.today()
TARGETS = sorted({dte for _, dte in chain_filter.DTE_TARGETS}, reverse=True)
key=_api_key()

# how many contracts per chosen monthly, unfiltered, with per-exp timing
t0=time.time(); center=_fetch_spot('SPX',key,30); t1=time.time()
print(f"_fetch_spot: {t1-t0:.2f}s  spot={center}")
chosen={}
for target in TARGETS:
    for cand in _monthly_candidates(today,target):
        if cand in chosen: break
        ts=time.time()
        s,cs=_fetch_expiration('SPX',cand,key,30)
        te=time.time()
        if cs:
            chosen[cand]=cs
            print(f"  target {target:>3}DTE -> {cand} : {len(cs):>4} contracts  {te-ts:.2f}s (unfiltered)")
            break
        else:
            print(f"  target {target:>3}DTE -> {cand} : NOT LISTED  {te-ts:.2f}s")
print(f"total contracts unfiltered: {sum(len(v) for v in chosen.values())}")
