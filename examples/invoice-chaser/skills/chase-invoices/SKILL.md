---
name: chase-invoices
description: "Draft a payment reminder for one overdue invoice. Use for each invoice past its due date, or when the owner asks to chase a client."
---

# Chase an invoice

1. Read the client's file `clients/<client>.md` (create it if missing): past reminders, disputes,
   preferred contact.
2. Disputed or a reminder sent in the last 7 days: stop.
3. Draft in the tone from the setup answers (`gentle`, `neutral`, `firm`):
   - subject: `Invoice <number>: payment reminder`;
   - amount, due date, payment link from Stripe;
   - one short paragraph, signed with the company name.
4. Save the draft to `outbox/<date>-<client>-<number>.md`, then send it.
5. Append a line to the client's file: `- <date> reminder <n> sent for <number>`.
