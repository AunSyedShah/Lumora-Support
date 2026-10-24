"""
What the email assistant can do, as tools for the Agno agent. Every tool is tied to ONE customer - the person
who wrote the email, identified by their registered address - when the toolset is built. The AI never
chooses who it is acting for, so it cannot read or change anyone else's complaints.
"""

from datetime import timedelta

from django.utils import timezone

from chatbot.service import find_excerpts
from complaints.models import Complaint
from complaints.schemas import ComplaintCustomerOut
from complaints.services import ComplaintValidationError, submit_complaint
from workflow.services import WorkflowError, auto_process, customer_reopen, customer_reply

MAX_LODGED_PER_EMAIL = 2
MAX_LODGED_PER_DAY = 5
MAX_UPDATE_CHARS = 600


def _when(value):
    return timezone.localtime(value).strftime("%d %b %Y, %H:%M") if value else None


class CustomerTools:
    """The tools handed to the agent. `lodged` and `touched` record what this one email changed."""

    def __init__(self, customer, config=None):
        self.customer = customer
        self.config = config
        self.lodged = []  # complaint ids created from this email
        self.touched = []  # complaint ids a message was added to

    def _mine(self, complaint_id):
        return Complaint.objects.filter(complaint_id=str(complaint_id).strip().upper(), customer=self.customer).first()

    # The docstrings below are what the AI reads to decide when to use each tool.

    def search_policies(self, question: str) -> str:
        """Look up Lumora's customer policies (returns, refunds, delivery, warranty, subscription, privacy ...).

        Use it for any general question about how Lumora works, before answering. Answer only from what it returns.

        Args:
            question: What the customer wants to know, in a few words.
        """
        excerpts, _sources = find_excerpts(question, self.config)
        return excerpts or "No matching policy was found. Do not guess; say you could not find it."

    def list_my_complaints(self) -> str:
        """List this customer's complaints, newest first, with their status. Use it when they ask about "my complaint" without saying which."""
        complaints = Complaint.objects.filter(customer=self.customer).select_related("department").order_by("-created_at")[:10]
        if not complaints:
            return "This customer has no complaints yet."
        out = []
        for c in complaints:
            view = ComplaintCustomerOut.from_orm(c)
            out.append(f"{c.complaint_id} - {c.title} - {view.resolution_status} - sent {_when(c.created_at)}")
        return "\n".join(out)

    def complaint_status(self, complaint_id: str) -> str:
        """Everything the customer is allowed to know about one of their complaints: status, team, escalation, the latest update and when we will reply.

        Args:
            complaint_id: The reference, like CMP-00012.
        """
        c = self._mine(complaint_id)
        if c is None:
            return f"This customer has no complaint {complaint_id}. Do not say anything about it; offer to list their complaints."
        v = ComplaintCustomerOut.from_orm(c)
        lines = [f"Complaint {c.complaint_id}: {c.title}", f"Status: {v.resolution_status}"]
        if v.department:
            lines.append(f"Handled by: {v.department}")
        lines.append(f"Escalated: {v.escalation.summary}" if v.escalation else "Escalated: no")
        if v.reply_expected_by:
            lines.append(f"We aim to respond by: {_when(v.reply_expected_by)}")
        if v.latest_update:
            lines.append(f"Latest update ({_when(v.latest_update['at'])}): {v.latest_update['text'][:MAX_UPDATE_CHARS]}")
        return "\n".join(lines)

    def lodge_complaint(self, title: str, description: str, order_ref: str = "") -> str:
        """Open a new complaint for this customer. Only when they clearly describe a problem they want handled, or ask to speak to a person.

        Write the description from what THEY said, in their words; add nothing they did not say. Never use it for plain questions.

        Args:
            title: A short summary, at least 5 characters.
            description: What happened, a few sentences, in the customer's own words.
            order_ref: The order number such as ORD-10042, only if they gave one.
        """
        since = timezone.now() - timedelta(days=1)
        if len(self.lodged) >= MAX_LODGED_PER_EMAIL or Complaint.objects.filter(customer=self.customer, channel=Complaint.Channel.EMAIL, created_at__gte=since).count() >= MAX_LODGED_PER_DAY:
            return "Not logged: too many complaints were opened from email today. Tell the customer the team will follow up."
        fields = {"title": title, "description": description, "product": None, "order_ref": order_ref or None,
                  "channel": Complaint.Channel.EMAIL, "preferred_contact": Complaint.ContactChannel.EMAIL,
                  "previous_complaint_ref": None, "requested_resolution": "", "supporting_information": ""}
        try:
            complaint, _warnings = submit_complaint(fields, customer=self.customer, submitted_by=self.customer)
        except ComplaintValidationError as e:
            existing = getattr(e, "existing_complaint", None)
            return f"Not logged: {e}" + (f" It is already complaint {existing}." if existing else "")
        auto_process(complaint)  # analysed, checked by the rules and routed, exactly like a complaint sent from the website
        complaint.refresh_from_db()
        self.lodged.append(complaint.complaint_id)
        due = _when(complaint.sla_response_due)
        return f"Logged as {complaint.complaint_id}." + (f" We aim to reply by {due}." if due else "")

    def add_to_complaint(self, complaint_id: str, message: str) -> str:
        """Add what the customer just wrote to one of their existing complaints, so the team sees it. A finished complaint is reopened if it is still within 7 days.

        Use it when they give more details, answer a question from the team, or say the problem is not fixed.

        Args:
            complaint_id: The reference, like CMP-00012.
            message: The customer's words to add.
        """
        c = self._mine(complaint_id)
        if c is None:
            return f"This customer has no complaint {complaint_id}."
        try:
            if c.status in (Complaint.Status.RESOLVED, Complaint.Status.CLOSED):
                customer_reopen(c, self.customer, message)
                result = f"{c.complaint_id} was reopened and the team will look at it again."
            else:
                customer_reply(c, self.customer, message)
                result = f"Added to {c.complaint_id}; the team will see it."
        except WorkflowError as e:
            return f"Not added: {e}"
        self.touched.append(c.complaint_id)
        return result

    def as_list(self):
        return [self.search_policies, self.list_my_complaints, self.complaint_status, self.lodge_complaint, self.add_to_complaint]
