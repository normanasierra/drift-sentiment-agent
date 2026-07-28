import time, datetime
import drift_sentiment.polygon_client as pc
from drift_sentiment import report as report_mod, chain_filter
today = datetime.date.today()
TARGETS = sorted({dte for _, dte in chain_filter.DTE_TARGETS}, reverse=True)
def W(w): return None if w is None else getattr(w,'strike',w)
def lv(rep): return {b.label:(W(b.call_wall),W(b.put_wall),W(b.magneto_strike),W(b.call_gamma_wall),W(b.put_gamma_wall),round(b.zero_gamma,3) if b.zero_gamma else None) for b in rep.buckets}

for tk in ['AAPL','SPY']:
    try:
        t0=time.time(); spot,cs=pc.fetch_chain_targeted(tk,today,TARGETS); t1=time.time()
        rep=report_mod.build_report(tk,spot,cs,today)
        print(f"{tk}: banded {t1-t0:.2f}s spot={spot} n={len(cs)}")
        # unfiltered comparison
        pc._band_frac_bak=pc._band_frac; pc._band_frac=lambda d:999.0
        spot2,cs2=pc.fetch_chain_targeted(tk,today,TARGETS); pc._band_frac=pc._band_frac_bak
        rep2=report_mod.build_report(tk,spot2,cs2,today)
        print(f"   unfiltered n={len(cs2)}  discrete+zeroG identical: {lv(rep)==lv(rep2)}  (band n={len(cs)})")
        if lv(rep)!=lv(rep2):
            for L in lv(rep): 
                if lv(rep)[L]!=lv(rep2)[L]: print("     DIFF",L,lv(rep)[L],lv(rep2)[L])
    except Exception as e:
        print(f"{tk}: ERROR {e}")
