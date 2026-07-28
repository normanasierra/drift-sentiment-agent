import time, datetime, statistics
import drift_sentiment.polygon_client as pc
from drift_sentiment import report as report_mod, chain_filter
today = datetime.date.today()
TARGETS = sorted({dte for _, dte in chain_filter.DTE_TARGETS}, reverse=True)

# --- OLD sequential re-implementation (verbatim from prior HEAD) for A/B identity ---
def fetch_seq(ticker, as_of, targets, timeout=30):
    key=pc._api_key(); chosen={}; spot=None
    for target in targets:
        resolved=False
        for cand in pc._monthly_candidates(as_of,target):
            if cand in chosen: resolved=True; break
            s,cs=pc._fetch_expiration(ticker,cand,key,timeout)
            if cs:
                chosen[cand]=cs
                if spot is None and s is not None: spot=s
                resolved=True; break
        if not resolved: raise pc.PolygonError(f"no monthly {target}")
    contracts=[c for cs in chosen.values() for c in cs]
    if spot is None: spot=pc._fetch_spot(ticker,key,timeout)
    return spot, contracts

def sig(contracts):
    # order-independent identity signature of the contract SET
    return sorted(repr((c.strike,c.expiration.isoformat(),c.contract_type,c.open_interest,
                   c.implied_volatility,c.price)) for c in contracts)

for tk in ['SPX','SPY','AAPL']:
    # concurrent timing (3 runs)
    tc=[]
    for _ in range(3):
        t0=time.time(); spotC,csC=pc.fetch_chain_targeted(tk,today,TARGETS); tc.append(time.time()-t0)
    # sequential timing (1 run) for A/B + identity
    t0=time.time(); spotS,csS=fetch_seq(tk,today,TARGETS); tseq=time.time()-t0
    same = sig(csC)==sig(csS)
    # build reports and compare exp sets
    expsC=sorted({c.expiration.isoformat() for c in csC}); expsS=sorted({c.expiration.isoformat() for c in csS})
    print(f"{tk}: concurrent median={statistics.median(tc):.2f}s (n={len(csC)})  sequential={tseq:.2f}s (n={len(csS)})  "
          f"speedup={tseq/statistics.median(tc):.2f}x  contract_set_identical={same}  exps_match={expsC==expsS}")
