# Automated Trading Strategy Backtester (Finance)

## The Problem
Quantitative researchers spend hours translating investment ideas into Python backtesting code (e.g., using libraries like Pandas or Backtrader). They often waste time fixing syntax errors, handling missing data, or adjusting parameters to make the script run.

## Desired Outcome
A web app where a user describes a trading strategy in plain English (e.g., *"Buy AAPL when the 50-day moving average crosses above the 200-day moving average, and sell when it crosses below"*).
- The agent writes the Python backtesting script.
- It executes the script against historical stock data.
- If there are errors or bugs, the agent reads the console traceback, fixes the code, and re-runs it.
- Once successful, it displays the performance metrics (Sharpe ratio, drawdowns) and charts to the user.

---

## Setup & Execution
Detailed implementation and running instructions go here.
