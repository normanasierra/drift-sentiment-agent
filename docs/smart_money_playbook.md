# Follow the Smart Money — Trade-Construction Playbook

*Distilled from the Najarian brothers' trade-construction chapters (Ch. 9 Stock
Replacement, Ch. 10 Vertical Spread, Ch. 11 Stock-Replacement Covered Call, plus
the F.R.A.M.E. / Greeks / Skews foundations). **Educational reference — not
financial advice.** Core premise throughout: the unusual option activity (UOA) is
**information about direction and timing**, not a contract you must copy.*

> **How this connects to the agent.** The *identification* half of the book (what a
> smart-money sweep looks like) is encoded in [`drift_sentiment/smart_money.py`](../drift_sentiment/smart_money.py)
> (the F.R.A.M.E. conviction score) and surfaced in the WhatsApp alerts, the daily
> brief, and the Wakanda **⚡ Actividad Inusual** tab. This document is the
> *construction* half — once you've decided to follow a sweep, how to actually
> structure the trade. `smart_money.follow_guidance()` is the one-line version of
> §1–§2 and §6 below.

## 1. Outright vs. Vertical vs. Stock-Replacement

The Najarians use an **outright long call/put or a vertical spread ~90% of the
time**. Pick the structure by what's making the option expensive:

| If… | Use | Trigger the book cites |
|---|---|---|
| You can **afford the outright option** | **Long call / long put** | "If you're able to afford the outright purchase of an option, do it." Don't cap gains you don't have to. The dividing line is personal (some won't pay >$3 for a speculative trade). |
| Stock is **high-priced** and/or **IV is too high**, so the outright is unaffordable | **Vertical (debit) spread** | High share price *and* pumped extrinsic launch premiums "into the stratosphere." AMZN 7/19/18: $1,813 stock, 8 DTE, ATM $1,812.50 call = **$53**; the 100-pt-OTM $1,912.50 = $16 but needed a **$116 move to break even**. "You can always buy a five-dollar spread for less than $5." |
| Option is **mid-priced** — too rich to just buy, not rich enough to force a vertical | **Stock-replacement covered call (diagonal)** | NFLX 8/20/18: $328 stock, ~30% IV, 18-day $320 call = **$14.22**. |
| You want to **control shares cheaply / hold a longer trend** with limited downside | **Stock replacement (deep-ITM call)** | Deep-ITM call = "insured shares" for a fraction of the cost. IBM: $130 call at **$16** controls 100 shares vs. $14,675 for shares+put — an **89% cost cut, 9:1 leverage**, no margin call. |

**Key idea:** a vertical is never a "worse" trade — it's the tool that lets you
take *some* position when the outright is unaffordable. "It's always better to have
some position than no position." A 50-cent OTM vertical that reaches its $5 max is a
**10-fold** return.

## 2. Strike Selection (ITM / ATM / OTM)

**What each distance signals** (delta ≈ probability of finishing ITM):

- **ATM (~50 delta):** all extrinsic value → breakeven pushed above spot; you need a
  fast move just to break even. **Most gamma**, **fastest theta decay**.
- **OTM (<50 delta):** even cheaper, needs an even bigger move → **lower probability**.
- **ITM (high delta):** behaves like stock; far enough ITM (no extrinsic) it performs
  *identically* to shares.

**Specific delta targets:**

- **Long-term stock replacement → 80–85 delta (deep ITM).** Find the ~**80–85 delta**
  strike and you're "in the ballpark." **Above 85Δ = diminishing returns:** on the IBM
  chain, going from $130 (82Δ, $16) to $125 cost **+$4.70 to cut extrinsic just $0.30**;
  to $120 cost **+$9.65 to cut extrinsic $0.35**. Each $5 deeper adds full intrinsic but
  sheds only pennies of extrinsic.
- **Short-term aggressive (fast spike expected) → calls ~65 delta, puts ~50 delta.**
  Lean on **gamma, not delta**: ATM + short-dated = richest gamma, so if you're right the
  deltas manufacture themselves, and if you're wrong there's less intrinsic to lose. Calls
  go *slightly* ITM (~65Δ) for a bit more delta while keeping gamma; **puts sit ATM
  (~50Δ)** because stocks "fall harder and faster than they rise" (staircase up, elevator
  down) and fear spikes put extrinsic — you want max gamma to capture it.

**The conviction / don't-chase nuance:**

- **Near-the-money UOA = conviction.** Stock at $100, heavy buying of the $110 "raises
  suspicions"; the $120 gives "even more confidence… the information is expected to be
  powerful." The **further OTM the smart money lines up, the bigger the signal — and the
  more aggressive** you can be.
- **But a far-OTM signal is low-probability — don't chase the same strike.** Stock at
  $100 with heavy $140 buying is a big signal, but if it doesn't reach $140 that option is
  "almost assuredly going to expire worthless." Play the **$110 or $120** instead, or use a
  **vertical** for the big far-OTM signals. Never buy a far-OTM strike just to make the
  option cheaper.

## 3. Expiration / DTE Selection

**Map DTE to the expected catalyst — the smart money won't buy a contract that
expires before the news:**

- **Follow the UOA's expiration.** Activity in the **30-day** contract → announcement
  likely within the month. A **weekly / within-the-week** → catalyst is imminent; buy the
  one-week structure (extend to the *following* week if the flagged week is extremely
  short-dated).
- **Short-term stock-replacement horizon: < 60 days**, sized for spikes of **5%, 10%, or
  more in a few days** — not a slow drift.
- **"Keep expirations as short as possible."** You want the spread at (or near) its
  **maximum value the moment the news hits.** When there's no exact match (only a 2-day and
  a 9-day listed), **take the longer** (the 9-day) so you don't expire before the event.
- **Match maturity to your horizon.** Expecting $100→$110 over a month? Buy **one-month**
  spreads. Too *long* → the slow-moving spread won't be near max value at your target. Too
  *short* → you can lose the week *and* have to roll into a now-pricier spread — a "double
  whammy."

## 4. Rolling Mechanics

**The rule and the math (rolling your own long call up as the stock rises):**

- **Roll when you can capture ~80% of the strike width.** A $5-wide roll ($100 → $105
  call) done for a **$4 credit**. Set a **limit at 80% of the strike difference** (roll to a
  $10-higher strike → limit ~$8). Rolling *is* a short vertical: "sell the $100/$105
  vertical."
- **What the $4-on-$5 roll buys you:** you own the $105 call (mkt $6) for a net **$2**;
  **max loss drops $6 → $2 (−66%)**; breakeven rises just **$1** ($106 → $107). Cost of the
  roll = width ($5) − credit ($4) = **$1**.
- **Timing guardrails:** don't roll **too early** (a $1 credit barely cuts your loss but
  shoves breakeven up $4); don't wait **too long** (a $20 roll for $16 credit leaves too much
  reversal room). Default: **every time you can get a $4 credit on a $5 roll.**
- **"Roll, roll, roll."** Each roll keeps you at ~**80 delta** — you never run out of
  "shares." Two $4 rolls on a $6 call = **$8 collected → a guaranteed 33% return** ("house
  money") while still holding a call for more upside.

**What a roll SIGNALS — follow the traders who've been right:** when the flagged trader
*rolls* a winner to a new strike instead of closing, they're **re-upping conviction** — a
stronger signal than the original trade. Book example — iShares Turkey (TUR), July 2018:
the Heat Seeker flagged **two bearish rolls in the same contracts within a week** (6,854
Jan $30 puts rolled down into 6,000 Jan $26 puts). TUR then **dropped ~15%** on Aug. 10 and
those puts roughly **tripled**. *(This is what `unusual_activity.detect_ladders()` looks
for: ≥2 same-direction strikes on one ticker.)*

## 5. Vertical Spread Construction

Same expiration, same type; **max gain + max loss always = the difference in strikes.**

**OTM vertical (both strikes OTM) — debit:**
- Trades at a **premium to intrinsic** (pure time value).
- **Positive gamma / negative theta** — you *need* the move; decay works against you.
- The usual UOA choice: expect fast moves ITM, and the low price lets you "load up."
  Halfway rule: stock **midway between the strikes** → spread costs **half the width**
  ($102.50 stock → $100/$105 ≈ $2.50).

**ITM vertical (both strikes ITM) — buy at a discount:**
- Trades at a **discount to intrinsic** (worth the full width at expiration, e.g. **$4
  today for a $5-wide**).
- **Positive theta / low gamma** — you **don't need the stock to move**; decay works **for
  you** as long as the stock doesn't fall.

**The safety rule — cost < difference in strikes.** Never pay **$4.90 for a $5-wide**
spread. Any price ≥ the width is a guaranteed loss.

**Debit call spread vs. credit put spread:** identical P&L. A credit spread is **not** free
income — the broker holds margin equal to the width. **Prefer the debit call spread when you
may want the "morph":** if the stock breaks out, buy back the short strike to convert into a
plain long call with **unlimited upside**. Never get left holding a **naked short**. Trade
verticals with **limit orders at the mid/mark**, never "at market."

## 6. IV Crush

**Do NOT chase the exact strike the UOA hit — its IV is already pumped.** As traders pile
into the same contract, "the extrinsic value gets bid up to abnormally high levels — and
sharp skews become present." The most-active strike carries the highest implied vol; the
authors "almost always use different strikes and expirations than the ones where the unusual
option activity is occurring for this very reason."

**Why it burns you — right on direction, still lose.** $100 stock, 30-day **$105 call at
$6 = 70% IV** (vs. 20% historical). News hits, stock jumps to **$107** — and the call
**falls to $3.80 (−36%)**. Extrinsic collapsed $6 → $1.80 as IV reverted 70% → ~22%. This is
the **volatility crush**. High IV is "like taking a football bet with a high point spread" —
the extrinsic *is* the spread, and it raises your breakeven.

**How to tell IV is elevated:** back out the option's implied vol and **compare it to the
stock's historical range.** Stock normally 20%, tops near 50% → a **70%** option is extremely
expensive *even at a $6 tag*. F.R.A.M.E. quick read: UOA at **25–30% when the stock is 20% =
not significant**; UOA at **70% = top of the list** (and a warning not to buy that strike).

**What to do instead:**
1. **Trade the direction/thesis, not the contract** — the UOA is just information.
2. **Pick your own strike and expiration** to sidestep the pumped strike's IV.
3. **Use a spread to cut the vega** — selling the short leg offsets the inflated IV, so the
   crush hurts far less. Vega is "one of the most powerful keys to unlocking the benefits of
   unusual option activity."
