# CODesk

A finance desk for a logistics company's daily cash-on-delivery (COD) work: driver handovers in cash and POS, POS checks against closed orders, driver expenses and advances, next-day bank deposits, and the daily finance report.

**All data in this project is fictional.** No real company, driver or bank data is used anywhere.

> Status: stage 5 of 6, work in progress. This file says exactly what works.

## The daily cycle it follows

1. Drivers finish their routes and hand over cash. Card payments were already taken on their POS machines.
2. The desk counts each driver's cash and checks it against the cash the delivery system says he collected.
3. POS payments are checked order by order against the orders closed in the system.
4. Travel expenses and advances are paid out of the day's cash.
5. The next working day, the rest of the cash goes to the bank: **cash to deposit = cash received - expenses paid**.
6. A daily finance report is produced.

## What works today

- **Login.** One owner account, scrypt password hashing, HttpOnly session cookie, lockout after five wrong passwords, and requests from unknown websites are refused.
- **Dashboard.** The chosen business day at a glance: total collected with the change against the previous day, the cash and POS split, cash and POS differences, and the day's money from driver to bank written as a ledger line (cash received, minus paid out, equals cash to deposit, minus deposited, equals pending). A 30-day chart of cash and POS per day (click a bar to open that day), the drivers with a difference on the day, and a "needs attention" list across all days: overdue or short deposits, unexplained POS differences, and advances open for more than 14 days, each linking to its page.
- **Reports.** The daily finance report and a period report (up to 93 days), as an Excel workbook (Summary, By day, Collections, POS check, Expenses and Deposits sheets, with real SUM formulas and formula-like text made harmless) or a printable one-page PDF with open items and Prepared / Checked / Approved sign-off lines. A preview shows the totals and what the report will list before you download it.
- **Collections.** Pick a business day (Fridays are skipped) and see every driver's handover: expected cash from the system, cash counted at the desk, the difference, POS card total and the day total. Short drivers are marked in red and extra cash in brass, and drivers who have not handed over yet are listed with a one-click record button. Handovers can be recorded, corrected or deleted, and every change is logged with the old and new amounts.
- **Import.** Upload the day's driver list as CSV or Excel. The file is checked first and nothing is saved until you confirm: unknown or inactive drivers, unreadable amounts, wrong order counts and the same driver twice are shown row by row. Rows already saved with the same values are skipped, and changed ones are updated. Column names are flexible ("Cash Collected", "System Cash", "Courier ID" and so on), amounts like "SAR 1,234.50" are understood, and dates are read day-first (26/10/2026). A template can be downloaded from the import window.
- **POS check.** For each driver and day, the orders the system shows as closed by POS against the total on his POS terminal, with the exact difference (terminal short or over). Click a driver to see his POS orders; an order whose amount equals the difference is highlighted, because it is usually the one closed as POS but paid in cash. Each difference can be marked explained (a reason is required) or needing follow-up, or reopened. If the numbers change after a review, the review shows as out of date and the difference is open again.
- **POS imports.** The system's POS-closed orders (order number, driver ID, amount; cash rows are skipped when the file has a payment method column) and the terminal sheet (terminal ID and the day's total, matched to drivers by terminal ID). Both are checked before anything is saved.
- **Expenses and advances.** Pay out fuel, tolls, parking, travel, maintenance or other expenses, or an advance, to a driver from the day's cash, with a receipt number and a note. Open advances are listed with how many days they have been open. An advance is recovered either by salary deduction (nothing comes back to the desk) or as cash returned at the desk, which is added to that day's cash to deposit. Recovered advances can be reopened, and cannot be changed or deleted until they are.
- **Bank deposits.** A day-by-day ledger: cash received, paid out, cash to deposit, deposited and pending. Each day's cash is due at the bank on the next working day (Fridays skipped), and every day shows one status: cash on hand, due today, overdue, deposit short, deposited or deposited too much, plus how many days late a deposit was. A day can be deposited with several slips; a slip number can only be used once, a slip cannot be more than what is still pending, and a deposit cannot be dated before its business day.
- **Drivers.** Add, edit, deactivate or reactivate drivers, each with his POS terminal ID (one terminal per active driver). Each handover remembers the terminal used that day, so moving a machine to another driver does not change old days. Each driver shows the last handover day, total cash shortages and advances not yet recovered. A driver with finance records cannot be deleted, only marked inactive.
- **Activity log.** Every change is saved with who made it and when. Entries cannot be edited or deleted (blocked in the database layer too).
- **Exact money.** Amounts are stored as whole halalas, so totals never drift the way decimal numbers in floating point do.
- **Fictional demo data.** 12 drivers and 30 working days (Fridays off) of handovers, expenses, advances and deposits, with mistakes planted on purpose so every check has something to find.

## Coming next

| Stage | What |
|---|---|
| 6 | Polish, screenshots and interview notes |

## The planted mistakes in the demo data

| Mistake | Where |
|---|---|
| Cash short | 5 handovers: 20, 50, 75, 120 and 300 SAR |
| Cash over | 1 handover: 30 SAR |
| Advances not recovered | 2 drivers: 300 and 800 SAR |
| Deposit short | 1 day: 500 SAR less than the cash to deposit |
| Late deposit | 1 day reached the bank 3 working days later |
| Not deposited yet | the latest day (due today) |
| POS terminal short | 3 driver-days: 60, 150 and 320 SAR |
| POS terminal over | 1 driver-day: 85.50 SAR (a card swiped twice) |

The tests check that the app finds exactly these.

`samples/sample_handovers.csv` is a fictional day you can import yourself. It has 9 good rows (one driver 50 short, one 20 over) and 2 rows with planted problems: an order count that is not a number and a driver ID that does not exist.

## Technology (all free)

React, TypeScript, Vite, Tailwind CSS, Recharts, Python, FastAPI, SQLAlchemy, SQLite, pandas, openpyxl, ReportLab, pytest, Vitest.

## Run it on Windows 11

You need Python 3.12 or 3.13 and Node.js 20 or newer. Use two PowerShell windows and run the commands one at a time.

**Window 1: backend**
```powershell
cd codesk\backend
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest
python -m uvicorn app.main:app --port 8000
```

**Window 2: frontend**
```powershell
cd codesk\frontend
npm install
npm test
npm run dev
```

Open http://localhost:5173 and create your owner account. The demo data is added the first time the backend starts with an empty database. To start again from fresh demo data, stop the backend and delete `backend\codesk.db`.

When a new version adds columns to the database, they are added automatically at start-up.

## How it is built

```
backend/app/
  main.py      API routes, login check, consistent error format
  models.py    database tables (money in halalas)
  money.py     reading amounts like "SAR 1,234.50" or "(500.00)" exactly
  seed.py      the fictional demo data and its planted mistakes
  auth.py      passwords and sessions
  audit.py     the activity log
frontend/src/
  pages/       one file per screen
  components/  layout, icons and shared pieces
```
