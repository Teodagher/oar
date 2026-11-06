# invoice-chaser (example template)

Follows up on unpaid invoices by email. A second worked example of the
[agent template format v0.2](../../SPEC.md), showing what the first one doesn't:

- a secret given to the agent as an environment variable (`Stripe` → `STRIPE_SECRET_KEY`), used by
  an MCP server through `${STRIPE_SECRET_KEY}` in `.mcp.json`;
- a secret written as a token file inside the agent's folder (`Gmail` →
  `.secrets/gmail-token.json`, from `secret-templates/gmail-token.json`);
- choice, number and boolean setup questions, used in a seed with `{{answer:…}}`;
- skills in `skills/`, the default location.

Check it with `python3 ../../tools/validate.py template .`
