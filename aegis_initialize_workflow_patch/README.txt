AEGIS PAPER PORTFOLIO INITIALIZATION WORKFLOW

File location in repository:
  .github/workflows/initialize-paper-portfolio.yml

Purpose:
- Manual-only initialization of the first $10,000 PAPER_ONLY ledger.
- Requires an explicit exact market date and a separate confirmation checkbox.
- Runs portfolio_initializer.py, which fetches exact-date daily closes for XLU, GRID and UTES.
- Saves simulation_ledger.json only after all quotes validate.
- Commits the ledger to the selected development branch.
- Refuses to run on main.

For the first initialization on 2026-11-18, the last completed US market session is 2026-11-17.
Enter 2026-11-17 as market_date. Do not use 2026-11-18 before that session has closed.

Before running:
- Confirm portfolio_initializer.py, market_data.py and simulation_engine.py are in the repository root.
- Confirm the initializer tests and all other tests are green.
- Confirm you are selecting branch aegis-simulation-rebuild.
- Confirm simulation_ledger.json does not already exist.

This workflow never contacts a broker and cannot place real orders.
