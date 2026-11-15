"""Dip-bounce breakout bot for the make.fun BTC 24h race.

Speaks agent-fun/bars-replay/v1 on stdin/stdout: one hello, one batch per
minute bar, then done. Answers every batch with exactly one reply echoing
its seq. Long only, one position, deterministic integer arithmetic only:
no randomness, no clock, no environment, no files.

Strategy, in short: wait for a washout, then buy the confirmed reversal.
A washout is a close at least 150 bps below the highest high of the last
60 bars. Confirmation is a close above every high of the previous 10 bars,
which means buyers have already reclaimed the short-term range instead of
the price still falling. Exits: a stop 80 bps under the fill, a target
300 bps over it, a 90 bps trailing stop once the trade is 50 bps in
profit, a 120-bar time stop, and a forced exit near the end of the
window. Size is capped at 40 bps of the latest close depth so the bot's
own price impact stays bounded even if the pool thins out, while still
using nearly the full stake on the deep, liquid bars where the entries
trigger.
"""

import json
import sys

# Strategy parameters, all in basis points unless noted.
LOOKBACK_BARS = 60
DROP_BPS = 150
BREAKOUT_BARS = 10
TAKE_PROFIT_BPS = 300
STOP_BPS = 80
HOLD_BARS = 120
TRAIL_BPS = 90
TRAIL_ARM_BPS = 50
MAX_SLIPPAGE_BPS = 100
SIZE_DEPTH_BPS = 40
FORCE_EXIT_SEQ = 1430
BPS = 10000


def main():
    hello = None
    symbol = None
    min_notional = 1000000
    warmup_bars = 0

    closes = []
    highs = []
    position_qty = 0
    cash = 0
    entry_px = None
    entry_seq = 0
    peak_px = 0

    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mtype = msg.get("type")

        if mtype == "hello":
            hello = msg
            symbols = msg.get("symbols") or []
            if symbols:
                symbol = symbols[0].get("symbol")
            fees = msg.get("fees") or {}
            try:
                min_notional = int(fees.get("min_notional_quote_units", min_notional))
            except (TypeError, ValueError):
                pass
            try:
                warmup_bars = int(msg.get("warmup_bars") or 0)
            except (TypeError, ValueError):
                warmup_bars = 0
            continue

        if mtype == "done":
            break

        if mtype != "batch":
            continue

        seq = msg.get("seq", 0)

        # Fills from the previous reply arrive in this batch. A filled buy
        # sets the entry price; a filled sell that empties the position
        # clears the trade state.
        for fill in msg.get("fills") or []:
            if fill.get("status") != "filled":
                continue
            if fill.get("symbol") != symbol:
                continue
            try:
                price = int(fill["price"])
            except (KeyError, TypeError, ValueError):
                continue
            if fill.get("side") == "buy":
                entry_px = price
                entry_seq = seq
                peak_px = price
            elif fill.get("side") == "sell":
                entry_px = None
                peak_px = 0

        # Authoritative account state.
        account = msg.get("account") or {}
        try:
            cash = int(account.get("cash_quote_units", cash))
        except (TypeError, ValueError):
            pass
        position_qty = 0
        for pos in account.get("positions") or []:
            if pos.get("symbol") == symbol:
                try:
                    position_qty = int(pos.get("qty", 0))
                except (TypeError, ValueError):
                    position_qty = 0
        if position_qty == 0:
            entry_px = None
            peak_px = 0

        # The bar that just closed, if this minute has one.
        bar = None
        for candidate in msg.get("bars") or []:
            if candidate.get("symbol") == symbol:
                bar = candidate
                break

        orders = []
        if bar is not None:
            try:
                close = int(bar["c"])
                high = int(bar["h"])
                c_depth = int((bar.get("c_depth") or ["0"])[0])
            except (KeyError, TypeError, ValueError, IndexError):
                close = None
            if close is not None:
                closes.append(close)
                highs.append(high)
                if position_qty > 0:
                    if entry_px is None:
                        # Fallback if a fill record was missed: anchor on
                        # the current close rather than trading blind.
                        entry_px = close
                        entry_seq = seq
                        peak_px = close
                    if close > peak_px:
                        peak_px = close
                    # Exit checks, worst case first.
                    drop_from_entry = (entry_px - close) * BPS
                    gain_from_entry = (close - entry_px) * BPS
                    giveback = (peak_px - close) * BPS
                    armed = gain_from_entry >= TRAIL_ARM_BPS * entry_px or \
                        (peak_px - entry_px) * BPS >= TRAIL_ARM_BPS * entry_px
                    trailing = armed and giveback >= TRAIL_BPS * peak_px
                    if (drop_from_entry >= STOP_BPS * entry_px
                            or gain_from_entry >= TAKE_PROFIT_BPS * entry_px
                            or trailing
                            or seq - entry_seq >= HOLD_BARS
                            or seq >= FORCE_EXIT_SEQ):
                        orders.append({
                            "side": "sell",
                            "client_id": "s%d" % seq,
                            "symbol": symbol,
                            "qty": str(position_qty),
                            "max_slippage_bps": MAX_SLIPPAGE_BPS,
                        })
                elif seq >= warmup_bars and len(highs) >= LOOKBACK_BARS + 1:
                    # Entry: washout plus confirmed breakout.
                    window_high = max(highs[-LOOKBACK_BARS:])
                    breakout_ref = max(highs[-BREAKOUT_BARS - 1:-1])
                    washed_out = (window_high - close) * BPS >= DROP_BPS * window_high
                    broke_out = close > breakout_ref
                    if washed_out and broke_out:
                        depth_cap = c_depth * SIZE_DEPTH_BPS // BPS
                        notional = cash if cash < depth_cap else depth_cap
                        if notional >= min_notional and notional >= 1:
                            orders.append({
                                "side": "buy",
                                "client_id": "b%d" % seq,
                                "symbol": symbol,
                                "notional_quote_units": str(notional),
                                "max_slippage_bps": MAX_SLIPPAGE_BPS,
                            })

        out.write(json.dumps(
            {"type": "reply", "seq": seq, "orders": orders},
            separators=(",", ":"),
        ))
        out.write("\n")
        out.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
