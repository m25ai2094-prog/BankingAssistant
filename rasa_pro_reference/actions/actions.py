from decimal import Decimal, InvalidOperation
from rasa_sdk import Action
from rasa_sdk.events import SlotSet

class ActionCheckTransfer(Action):
    def name(self):
        return "action_check_transfer"

    def run(self, dispatcher, tracker, domain):
        balance = Decimal("1000.00")
        raw_amount = tracker.get_slot("amount")
        try:
            amount = Decimal(str(raw_amount))
            if (
                not amount.is_finite()
                or amount <= 0
                or amount != amount.quantize(Decimal("0.01"))
            ):
                status = "invalid"
            elif amount > balance:
                status = "insufficient"
            else:
                status = "valid"
        except (InvalidOperation, ValueError, TypeError):
            status = "invalid"
        return [SlotSet("transfer_status", status)]
