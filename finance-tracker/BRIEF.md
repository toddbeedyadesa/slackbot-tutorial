# Personal & Business Finance Tracker — Build Brief

## Purpose
One app to track income and expenses across several businesses, a W-2 job, and nonprofit/volunteer spending, combined into one picture.
Goals: (1) see where money is going, (2) find where money can be saved.

## Platform
- Responsive web app, usable on phone and desktop from the same synced data. One backend, build once.
- Not a native phone app to start; it can be wrapped to feel app-like later.

## Core design principle
Every transaction, however it enters (manual entry, CSV import, or bank feed), is stored in ONE shared internal transaction format.
All tagging, reports, and views read from that format and never depend on the source.
This keeps adding the bank connector and new reports easy later.

## Transaction fields
- Date
- Amount
- Description
- Entity (see list below)
- Category (see list below)
- Source: manual / csv / bank
- Unique ID (used for deduplication)
- Reimbursable: yes / no

## Entities (each has a type)
| Entity | Type |
|---|---|
| Carvana | W-2 |
| Environmental Vanguardians | Business |
| Paul's Pipe Shop | Business |
| D&T Computer Consultants | Business |
| American Legion | Nonprofit |
| Spiritual Warfare Unit | Nonprofit |
| Personal | Personal |

Entities should be editable (add, rename, archive) without code changes.

## Categories (each belongs to a parent group)
- **Utilities:** Electric, Gas, Water, Internet, Cell Phone
- **Food:** Groceries (food eaten at home), Dining Out (restaurants, takeout)
- **Transportation:** Fuel & Vehicle
- **Other:** Insurance, Software & Subscriptions, Professional Services, Repairs & Maintenance, Taxes & Licensing, Supplies, Equipment, Travel, Advertising & Marketing, Rent or Lease, Housing, Healthcare, Giving / Donations, Other (catch-all)

Categories and parent groups should be editable without code changes. Reports can show either the parent group or the detailed category.

## Build stages (finish each before starting the next)
1. **Design:** the transaction format, entities with types, and categories with parent groups described above.
2. **Minimum working app:** add a transaction manually, see a running list, tag each one with an entity and a category, set the reimbursable flag, and view combined and per-entity reports.
3. **Import & connect:** CSV import for bulk bank history, then Plaid (free Trial plan, up to 10 connected accounts) for live bank feeds. Include deduplication so manual and bank-fed copies of the same transaction don't double count.

## Bank connection notes
- Use an aggregator (Plaid in the US; MX or Finicity as alternatives). Never handle bank credentials directly.
- Plaid's free Trial plan covers personal use (up to 10 connected accounts). Paid per-account pricing only matters if this becomes a product for other users.
- Bank feeds sometimes break, so manual entry and CSV import must stay reliable, first-class options.

## Reports (initial set)
- Spending by category (parent groups with drill-down)
- Spending by entity (W-2 vs. business vs. nonprofit vs. personal)
- Month-over-month trends
- Recurring subscriptions
- Reimbursable summary (what is owed, and by whom)

Build reporting so new report views are easy to add. Reports only read the shared transaction data and should never need structural changes.

## Future direction
The core engine (one transaction format with entities, categories, and reports) should be reusable for possible future modules, such as a freelancer tax module or a rental property module. Don't build modules now; just avoid design choices that would block them later.
