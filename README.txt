AEGIS PORTFOLIO INITIALIZER PATCH

Files:
- portfolio_initializer.py (repository root)
- tests/test_portfolio_initializer.py (inside existing tests/ folder)

This connects the existing market_data.py adapter to simulation_engine.py.
It requires an explicit market date, fetches all required opening quotes as
one all-or-nothing batch, creates a PAPER_ONLY ledger, and refuses to overwrite
an existing ledger by default. It never submits broker orders.

Do not run initialization until the chosen date and fetched XLU, GRID, UTES
quotes have been reviewed. Synthetic quotes in tests are not market prices.

After installing and testing, a deliberate manual initialization command is:
  python portfolio_initializer.py --date YYYY-MM-DD --confirm

The date must be replaced with the intended actual market date. The script
will fail closed if Yahoo Finance does not return exact-date bars.

Run all tests from repository root:
  python -m unittest discover -s tests -v
