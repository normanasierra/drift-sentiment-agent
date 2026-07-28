import time, datetime, json, pprint
from drift_sentiment import polygon_client, report as report_mod
today = datetime.date.today()

def W(w):
    if w is None: return None
    return getattr(w, 'strike', w)

def levels(rep):
    out={"spot":round(rep.spot,6)}
    for b in rep.buckets:
        out[b.label]={
          "actual_dte": b.actual_dte,
          "expiration": str(b.expiration),
          "call_wall": W(b.call_wall),
          "put_wall": W(b.put_wall),
          "magneto_strike": W(b.magneto_strike),
          "magneto_notional": round(b.magneto_notional,4) if b.magneto_notional is not None else None,
          "zero_gamma": round(b.zero_gamma,6) if b.zero_gamma is not None else None,
          "call_gamma_wall": W(b.call_gamma_wall),
          "put_gamma_wall": W(b.put_gamma_wall),
          "total_gex": round(b.total_gex,4) if b.total_gex is not None else None,
          "sigma": round(b.sigma,6) if b.sigma is not None else None,
        }
    return out

spot, contracts = polygon_client.fetch_chain('SPX')
rep_full = report_mod.build_report('SPX', spot, contracts, today)
base=levels(rep_full)
pprint.pprint(base)
json.dump(base, open('scratch_full.json','w'), indent=2, default=str)
