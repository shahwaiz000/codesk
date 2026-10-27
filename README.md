# CODesk

A finance desk for a logistics company's daily cash-on-delivery (COD) work: driver handovers in cash and POS, POS checks against closed orders, driver expenses and advances, next-day bank deposits, and the daily finance report.

**All data in this project is fictional.** No real company, driver or bank data is used anywhere.

> Status: stage 2 of 6, work in progress. This file says exactly what works.

## The daily cycle it follows

1. Drivers finish their routes and hand over cash. Card payments were already taken on their POS machines.
2. The desk counts each driver's cash and checks it against the cash the delivery system says he collected.
3. POS payments are checked order by order against the orders closed in the system.
4. Travel expenses and advances are paid out of the day's cash.
5. The next working day, the rest of the cash goes to the bank: **cash to deposit = cash received - expenses paid**.
6. A daily finance report is produced.

## What works today

- **Login.** One owner account, scrypt password hashing, HttpOnly session cookie, lockout after five wrong passwords, and requests from unknown websites are refused.
- **Collections.** Pick a business day (Fridays are skipped) and see every driver's handover: expected cash from the system, cash counted at the desk, the difference, POS card total and the day total. Short drivers are marked in red and extra cash in brass, and drivers who have not handed over yet are listed with a one-click record button. Handovers can be recorded, corrected or deleted, and every change is logged with the old and new amounts.
- **Import.** Upload the day's driver list as CSV or Excel. The file is checked first and nothing is saved until you confirm: unknown or inactive drivers, unreadable amounts, wrong order counts and the same driver twice are shown row by row. Rows already saved with the same values are skipped, and changed ones are updated. Column names are flexible ("Cash Collected", "System Cash", "Courier ID" and so on), amounts like "SAR 1,234.50" are understood, and dates are read day-first (26/10/2026). A template can be downloaded from the import window.
- **Drivers.** Add, edit, deactivate or reactivate drivers. Each driver shows the last handover day, total cash shortages and advances not yet recovered. A driver with finance records cannot be deleted, only marked inactive.
- **Activity log.** Every change is saved with who made it and when. Entries cannot be edited or deleted (blocked in the database layer too).
- **Exact money.** Amounts are stored as whole halalas, so totals never drift the way decimal numbers in floating point do.
- **Fictional demo data.** 12 drivers and 30 working days (Fridays off) of handovers, expenses, advances and deposits, with mistakes planted on purpose so every check has something to find.

## Coming next

| Stage | What |
|---|---|
| 3 | POS reconciliation: closed orders against POS transactions, exact differences, approve or reject |
| 4 | Expenses and advances, and bank deposits with pending amounts |
| 5 | Dashboard and the daily finance report (Excel and PDF) |
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

The tests check that the app finds exactly these.

`samples/sample_handovers.csv` is a fictional day you can import yourself. It has 9 good rows (one driver 50 short, one 20 over) and 2 rows with planted problems: an order count that is not a number and a driver ID that does not exist.

## Technology (all free)

React, TypeScript, Vite, Tailwind CSS, Python, FastAPI, SQLAlchemy, SQLite, pandas, pytest, Vitest.

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
