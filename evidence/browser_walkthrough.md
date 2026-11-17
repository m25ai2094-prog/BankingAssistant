# Browser walkthrough

The redesigned interface was exercised on 15 November 2026 in Chromium on Linux against a fresh local SQLite fixture. The project uses fictional accounts. The automated results in `summary.json` use a separate fixture and generate their own references.

| Step | Observed result |
| --- | --- |
| Open Overview and choose Transfers | All services showed 15 entries. Transfers showed one service. |
| Start Transfer money and verify DEMO1001 | The code appeared in the Demo inbox. A successful submission advanced to beneficiary selection. |
| Select Meera Rao, 1500, IMPS and Personal | The pinned review showed ₹1,500.00 and beneficiary suffix 2002. |
| Return to Overview and choose Resume request | The assistant reopened the pending review. |
| Choose Change amount and review 1600, then restore 1500 | Both revised amounts appeared after the rail and purpose were entered again. |
| Submit unrelated text at review | The assistant requested a confirmation decision and preserved the review. |
| Reload the browser and confirm | The pending review and its controls were restored. Confirmation produced TRF-BDAFE5AA91 with the status Recorded in sandbox. |
| Inspect sending and receiving balances | DEMO1001 showed ₹1,23,500.00. After switching and verifying DEMO1002, the recipient showed ₹69,500.00. |

`figures/redesigned_overview.jpg` shows the dashboard before verification. `figures/redesigned_review.jpg` shows a separately staged review with the same input values. That second draft was cancelled after capture.

The Windows batch source was inspected. Browser and extraction checks ran on Linux.
