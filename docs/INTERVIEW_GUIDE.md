# CODesk: interview notes

Notes for presenting CODesk to an employer. Read them a few times, then say it in your own words. Don't learn them by heart.

## The 30-second version

> At my job I'm the person drivers hand their COD cash to at the end of the day. I count it, check their POS totals against the orders closed in the system, pay out fuel and advances, and deposit the cash the next day. I did all of this in Excel sheets, and mistakes were easy to miss. So I built CODesk: a small web app that follows that same day step by step, shows every difference to the halala, makes you write a reason before you close one, and prints the daily report ready to sign.

## The problem it solves

- **Cash shortages hide in big totals.** One driver 50 short is invisible in a 40,000 SAR day. CODesk checks every driver against what the system expected.
- **POS differences are slow to trace.** The terminal shows one total and the system shows a list of orders. CODesk puts them side by side, and if one order equals the difference it highlights it. That's usually the order closed as POS but paid in cash.
- **Deposits get forgotten or come up short.** Each day's cash is due the next working day. CODesk shows what's due today, what's overdue and what was deposited short.
- **Advances get lost.** Every open advance stays on the list with its age until it's recovered from salary or returned in cash.
- **Nobody knows who changed what.** Every change is logged with the name, the time and the old and new amounts, and the log can't be edited.

## A 5-minute demo

Start from a fresh database (delete `backend\codesk.db`, start the backend, create the account).

1. **Dashboard (30 s).** "This is yesterday. Cash received, minus what I paid out, is what goes to the bank, and nothing is deposited yet, so it's due today. On the right is everything still open across all days."
2. **Collections (1 min).** Click *Today* in the day strip, then *Import file* with `samples/sample_handovers.csv`. "It checks the file before saving anything. Here it caught an order count that isn't a number and a driver ID we don't have." Save the 9 good rows. "Yousef is 50 short and Naveed handed over 20 extra."
3. **POS check (1.5 min).** Import `sample_pos_orders.csv`, then `sample_terminal_sheet.csv`. "The cash order in the export is skipped, and the terminal that belongs to nobody is flagged." Open D-105: "The terminal is 275 short. One order is exactly 275, so that's the one to ask the driver about." Write a reason and mark it explained. "Saeed's terminal is 50 over, probably a card swiped twice, so I'd mark that for follow-up."
4. **Expenses (30 s).** Pay out a fuel expense. Show the open advances list and the *Recover* choice: salary or cash at the desk.
5. **Bank deposits (1 min).** "Thursday's cash goes in on Saturday because Friday is off." Record yesterday's deposit. Point at the short day: "500 missing from this slip, and it stays red until someone deals with it."
6. **Reports (30 s).** Download the daily PDF. "One page with signature lines for prepared, checked and approved. Excel has the same numbers with real formulas, so finance can work with it."

## Design decisions you can explain

- **Money in halalas, not decimals.** "Computers store 0.10 inexactly as a decimal number. If you add thousands of amounts, totals can be off by a fraction. I store every amount as whole halalas, so 1,234.50 SAR is 123450, and totals are always exact."
- **Check before saving.** "Every import shows what will happen first: new, updated, already saved, or a problem with the reason. Bad rows are never saved. In finance a half-imported file is worse than no import."
- **A reason is required to close a difference.** "You can't just make a difference disappear. Explaining it needs a note, and if the numbers change later, the explanation shows as out of date."
- **The log can't be edited.** "The activity log only accepts new entries. Even the database layer refuses edits or deletions, because an audit trail you can edit isn't an audit trail."
- **The terminal is stored on each day.** "POS machines move between drivers. Each handover keeps the terminal used that day, so old days don't change when a machine is reassigned."
- **One calculation, used everywhere.** "The dashboard, the deposits page and the reports all use the same function for cash to deposit, so the numbers can never disagree."
- **Planted mistakes in the demo data, checked by tests.** "I know exactly which mistakes are in the data. The tests check the app finds those and nothing else. That's how I know the logic is right, not just that it looks right."

## Questions you may be asked

**Why not just Excel or Power BI?**
"Excel is great for analysis, and the reports still export to Excel. But a daily process needs things Excel doesn't enforce: one record per driver per day, a reason before closing a difference, a log nobody can edit, and checks before data goes in. Power BI shows the results; this is where the work happens."

**What was the hardest part?**
Pick one you can talk about honestly. A good one: "Getting the POS check right. At first I thought it should match each payment to each order. Then I realised that at my desk we only see one terminal total per day, so the real check is the driver's system total against his terminal total, with the order list for finding the cause."

**How do you know the numbers are right?**
"71 backend tests and 11 frontend tests. The demo data has planted mistakes with known answers, and the tests check them, including that the dashboard, deposits page and reports all agree."

**How would it work with real data?**
"The imports accept the exports a delivery system and a POS provider already give you, with flexible column names. For real use I'd add user accounts with roles, move from SQLite to PostgreSQL, and run it on a company server with HTTPS."

**What would you add next?**
"Roles (a cashier records, a supervisor approves), a hub filter, partial advance recovery, and an Arabic interface."

**Did you use AI to build it?**
Be honest. Something like: "Yes, I used an AI coding assistant for much of the code. The workflow, the rules and the test cases come from my own job, and I tested every step on my laptop. I can walk you through any part of it." Then make sure you can: open the code for one feature (for example `backend/app/deposits.py`) and explain what it does in plain words.

## Numbers to remember

- 6 working screens plus Drivers and Settings
- 3 kinds of import, all checked before saving
- 71 backend tests, 11 frontend tests
- 12 fictional drivers, 30 working days, 14 planted mistakes plus the latest day waiting to be deposited
- Built with React, TypeScript, Tailwind, Python, FastAPI, SQLite. All free tools.

## What to say for a data or business analyst role

"The app is really a data pipeline with a person in the loop. Raw files come in, get cleaned and validated, are matched against each other, and the exceptions go to someone to decide. The results come out as a dashboard and as reports. That's the same thinking I'd bring to analysis work: get the data right first, make the differences visible, and keep a record of every decision."
