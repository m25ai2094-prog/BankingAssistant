# Earlier Rasa Pro CALM transfer example

These code listings were recovered from Rakesh Jaiswal's earlier MTP-II report, appendices A–D. They document the observed transfer prototype using a fixed fictional balance of INR 1,000. The saved Inspector and terminal captures are in `../figures/`.

The earlier workflow ran in the student's Rasa Pro tutorial project. To reproduce it, open that project in its existing licensed environment or start from the matching Rasa Pro tutorial. Preserve its tutorial patterns and apply the included `config.yml`, `endpoints.yml`, `domain.yml`, `actions/` and `data/flows.yml`. Set your own private Rasa licence in that terminal, then run `rasa train` and `rasa inspect`. The tutorial command-generation endpoint requires access to the service. Keep licence material outside the project archive.

The included `validation_harness.py` independently checks the earlier monetary validation using only Python. It can be run with `python validation_harness.py` and passed 16 component cases in this workspace. It exercises the Decimal rules. The expanded offline project runs from the parent folder with `python run.py`, and its held-out and workflow results are reported separately in `../evidence/`.
