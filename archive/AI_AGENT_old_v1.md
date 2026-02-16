# AI_AGENT.md

## Crypto Regime Trading App (Coinbase + BTC)

------------------------------------------------------------------------

# Project Overview

This project builds a fully automated crypto trading system focused on:

-   BTC-USD (Coinbase Advanced)
-   5-minute candles
-   5--120 minute trade duration
-   Regime-based routing (Trend vs Mean Reversion × Volatility)
-   Machine Learning-assisted regime detection
-   Strict risk management
-   Walk-forward validation
-   Paper engine first, live deployment later

This is NOT a high-frequency trading system. This system does NOT
compete on microseconds. This system competes on structure, volatility,
and regime behavior.

------------------------------------------------------------------------

# Core Philosophy

1.  No curve fitting.
2.  No leakage.
3.  Walk-forward validation only.
4.  Risk control before returns.
5.  Capital scaling only after proof.

------------------------------------------------------------------------

# System Architecture

## 1) Data Layer

-   Pull 5-minute BTC-USD candles via Coinbase API
-   Store locally (SQLite recommended)
-   Maintain rolling historical dataset (minimum 2 years)

## 2) Feature Engineering

### Trend Measurement (Efficiency Ratio)

Lookback: 20 bars (100 minutes)

ER = abs(close\[t\] - close\[t-n\]) / sum(abs(close\[i\] -
close\[i-1\]))

Regime Thresholds: - Trend: ER \>= 0.35 - Mean Reversion: ER \<= 0.25 -
Between 0.25--0.35 = Uncertain

### Volatility Regime

Compute rolling standard deviation of returns over 48 bars (\~4 hours).

Define percentiles over long rolling window (60 days): - High Vol: RV \>
70th percentile - Low/Normal Vol: RV \<= 70th percentile - Ultra-high
(optional): \> 90th percentile

### No-Trade Zone

If ER \< 0.20 AND RV \> 80th percentile → No trade.

------------------------------------------------------------------------

# Regime Definitions

A)  Trend + Low/Normal Vol\
B)  Trend + High Vol\
C)  Mean Reversion + Low/Normal Vol\
D)  Mean Reversion + High Vol\
E)  Optional: No Trade

------------------------------------------------------------------------

# Machine Learning Rules

## Phase 1: Regime Classifier

Goal: Predict probability of Trend vs Mean Reversion (and optionally
High Vol).

Allowed Models: - Logistic Regression - Random Forest - Gradient
Boosting (later)

NOT allowed initially: - Deep neural networks

### Strict ML Rules

1.  No future leakage.
2.  Only use data available at decision time.
3.  Walk-forward validation only.
4.  No random train/test split.
5.  Retrain weekly maximum.
6.  Do not auto-deploy new model without validation.
7.  Use uncertainty band (0.45--0.55 probability = no trade).

------------------------------------------------------------------------

# Expert Strategy Routing

After regime prediction:

If Trend → Route to Trend Expert\
If Mean Reversion → Route to Mean Reversion Expert\
If Uncertain → No trade or reduced size

------------------------------------------------------------------------

# Example Expert Logic (Initial Rule-Based Version)

## Trend Expert (Prototype)

-   Enter breakout above recent range high (lookback 10 bars)
-   Stop: 1 ATR
-   Target: 1.5--2 ATR
-   Position size: 0.5--1% account risk

## Mean Reversion Expert (Prototype)

-   Enter when price deviates from VWAP by \> 1.5 std dev
-   Exit at VWAP touch or fixed R:R
-   Stop: 1 ATR
-   Risk: 0.5--1%

------------------------------------------------------------------------

# Risk Management

-   Risk per trade: 0.5--1%
-   Max daily drawdown: 3%
-   Max 3 trades per day
-   If daily loss cap hit → Stop trading
-   If system state uncertain → Flatten or Halt

------------------------------------------------------------------------

# Paper Engine Requirements

Simulated fills must include:

-   Spread modeling
-   Slippage modeling
-   Limit-first logic
-   Order timeout handling
-   Fill reconciliation
-   Logging of every decision

Paper test duration: Minimum 4--8 weeks before live deployment.

------------------------------------------------------------------------

# Live Deployment Rules

Only go live if:

-   Walk-forward positive expectancy
-   Controlled max drawdown
-   Stable performance across regimes
-   No catastrophic model drift

Initial capital: \$500\
Initial risk per trade: \<=1%\
Scale capital only after stable equity curve.

------------------------------------------------------------------------

# Long-Term Plan

Stage 1: BTC Spot on Coinbase Advanced

Stage 2: Improve ML regime detection

Stage 3: Port architecture to MNQ Futures

Stage 4: Scale capital

------------------------------------------------------------------------

# Non-Negotiables

-   No revenge trading
-   No parameter brute forcing
-   No changing system mid-drawdown
-   No increasing risk to "make it back"
-   All changes logged and versioned

------------------------------------------------------------------------

# Development Order

1.  Build data ingestion + storage
2.  Implement feature computation
3.  Implement rule-based regime classification
4.  Backtest rule-only version
5.  Add ML regime classifier
6.  Implement expert strategies
7.  Build paper execution engine
8.  Forward test
9.  Deploy small live
10. Scale gradually

------------------------------------------------------------------------

End of AI_AGENT.md
