import time, datetime, json
from drift_sentiment import polygon_client, report as report_mod, chain_filter
_TARGETS = sorted({dte for _, dte in chain_filter.DTE_TARGETS}, reverse=True)
today = datetime.date.today()

t0=time.time()
spot, contracts = polygon_client.fetch_chain('SPX')
t1=time.time()
print(f"FULL fetch_chain SPX: {t1-t0:.2f}s spot={spot} n={len(contracts)}")
rep_full = report_mod.build_report('SPX', spot, contracts, today)

def levels(rep):
    out={"spot":round(rep.spot,4)}
    for b in rep.buckets:
        out[b.label]={
          "call_wall": b.call_wall.strike if b.call_wall else None,
          "put_wall": b.put_wall.strike if b.put_wall else None,
          "magneto": getattr(b,'magneto',None) and b.magneto.strike,
          "zero_gamma": round(b.zero_gamma,4) if getattr(b,'zero_gamma',None) else None,
          "gamma_call_wall": getattr(b,'gamma_call_wall',None) and b.gamma_call_wall.strike,
          "gamma_put_wall": getattr(b,'gamma_put_wall',None) and b.gamma_put_wall.strike,
        }
    return out

print("BUCKET attrs:", [a for a in dir(rep_full.buckets[0]) if not a.startswith('_')])
import pprint
base=levels(rep_full)
pprint.pprint(base)
json.dump(base, open('scratch_full.json','w'), indent=2, default=str)
