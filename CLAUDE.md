# Squarelet

## Code comments

Comments say **why**, not what. If the code already says it, delete the
comment.

- **One or two short sentences.** If it needs a paragraph, it belongs in a
  docstring, the PR description, or a doc under `docs/`.
- **Keep the consequence, drop the lead-in.** The clause naming what the
  code does is the half to cut; the clause saying what breaks otherwise is
  the half worth keeping.
- **Never describe code that is not there.** No "this used to...", no
  narrating the change, no explaining why something was removed. `git log`
  and the PR hold that.
- **No reasoning out loud.** Don't walk through scenarios, anticipate
  objections, or record the thought process behind a choice.
- **Do comment the surprising**: a constraint Stripe imposes, an ordering
  requirement, a failure that cannot be seen locally. That is what a
  reader cannot get from the code.

```python
# Good - a constraint you cannot see from here
# Stripe rejects a subscription whose items have different intervals.

# Bad - narrates the change
# `next_date` is a property on the line now, reading its subscription's -
# assigning to it raises, and this page is the only caller that did.

# Bad - the first sentence is the code read aloud
# Cancellation is owned by cancel(), uncancel() and the Stripe webhook -
# clearing it here would revive a cancelled subscription.

# Good - only the half you cannot see
# Clearing this here would revive a cancelled subscription on any
# unrelated line change.
```

## Docstrings

One line on what it does. Add more only for a contract a caller needs:
what it raises, what it returns in the edge case, ordering it requires,
side effects it has, a query cost worth avoiding.

Two tests before you keep a second paragraph:

- Does it restate the first line in more words? Delete it.
- Would a caller behave differently for knowing it? Keep it, in one or two
  sentences.

```python
# Good - the whole contract, one line
"""Does the subscription renew?  True while any line still does."""

# Good - a second paragraph a caller acts on
"""The date this subscription next renews, or ends if cancelled.

Read from the cached `current_period_end`; the billing pages render one
row per line and cannot afford a Stripe call each.
"""
```

## Pull request descriptions

Open with one sentence on what changes. Then:

- **Behaviour changes** — name them, or say "none".
- **Migrations** — what they do, whether they reverse.
- **What to check** — the QA steps, as a checklist.

Bullets, not prose. Don't recount how the change came about or what was
tried first.

## Tests

Name the behaviour, not the mechanism: `test_a_free_line_survives_the_cancellation`,
not `test_delete_branch`. A test whose assertion would pass against the
unfixed code is not a test.

## Running things

`inv test --path "squarelet -q -p no:sugar"` - add `--create-db` when the
schema has moved. `inv pylint` for lint, `inv format` for black and isort;
CI checks both. `inv test-stripe` runs the sandbox suite against real
Stripe and is required before any release that touches it.
