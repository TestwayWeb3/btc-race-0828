# Dip-Bounce Breakout Bot

A trading bot for the make.fun competition `btc-race-24h-20261115-0828`
("Race a BTC trading bot live for 24 hours"). It trades CBBTC against
USDC on one-minute bars, long only, starting from 1,000 USDC of paper
money, speaking the `agent-fun/bars-replay/v1` line protocol on stdin
and stdout. Python standard library only; the logic is deterministic
integer arithmetic, with no randomness, no clock, no environment reads,
and no file access.

## Strategy

Wait for a washout, then buy the confirmed reversal. A washout is a
close at least 150 basis points below the highest high of the last 60
bars. Confirmation is a close above every high of the previous 10 bars:
buyers have already reclaimed the short-term range, so the bot is not
catching a price that is still falling. The bot holds at most one
position.

Exits: a stop 80 basis points under the fill price, a target 300 basis
points over it, a 90 basis point trailing stop that arms once the trade
is 50 basis points in profit, a 120-bar time stop, and a forced exit
near the end of the window. Order size is capped at 40 basis points of
the latest close depth, so the bot's own price impact stays bounded
even if the pool thins out. Every order names a 100 basis point maximum
slippage from the latest close it was sent.

## Verification

A standalone replay harness (kept outside this repository) feeds the
bot the frozen 1,440-bar dev window through the same protocol and
applies the documented fill model: next-bar-open fills, 4 bps fee,
2 bps modelled slippage, constant-product impact against open depth,
and a flattening sale at the last close. On the dev window the bot
finishes with a net profit of about 29.68 USDC after all costs, from a
single round trip, with maximum drawdown under 1%, and two runs
produce byte-identical action logs.
