# Squarelet

<!-- AGENTS.md shared standard v2 — canonical copy: https://github.com/MuckRock/gps/blob/main/AGENTS.md -->

## Code comments

Comments say **why**, not what. If the code already says it, delete the comment.

- **One or two short sentences.** If it needs a paragraph, it belongs in a
  doc comment, the PR description, or a doc under `docs/`.
- **Keep the consequence, drop the lead-in.** The clause naming what the
  code does is the half to cut; the clause saying what breaks otherwise is
  the half worth keeping.
- **Never describe code that is not there.** No "this used to...", no
  narrating the change, no explaining why something was removed. `git log`
  and the PR hold that.
- **No reasoning out loud.** Don't walk through scenarios, anticipate
  objections, or record the thought process behind a choice.
- **Do comment the surprising**: a constraint an external system imposes,
  an ordering requirement, a failure that cannot be seen locally. That is
  what a reader cannot get from the code.

```typescript
// Good - a constraint you cannot see from here
// The API rejects a redaction whose page range crosses a document split.

// Bad - narrates the change
// `currentPage` is now derived from the store instead of a prop, so
// this component no longer needs to read it from context.
```

## Docstrings / doc comments

One line on what it does. Add more only for a contract a caller needs: what it rejects/throws, what it returns in the edge case, ordering it requires, side effects it has, a cost worth avoiding.

Two tests before you keep a second paragraph:

- Does it restate the first line in more words? Delete it.
- Would a caller behave differently for knowing it? Keep it, in one or two sentences.

```typescript
// Good - the whole contract, one line
/** Does the document still have pages pending OCR? */

// Good - a second paragraph a caller acts on
/**
 * The document's current processing status, or "error" if any page failed.
 *
 * Read from the cached store value; the document list renders one row
 * per document and cannot afford an API call each.
 */
```

## Pull request descriptions

Open with one sentence on what changes. Then:

- **Behaviour changes** — name them, or say "none".
- **Migrations** — what they do, whether they reverse.
- **What to check** — the QA steps, as a checklist.

Bullets, not prose. Don't recount how the change came about or what was tried first.

## Tests

Name the behaviour, not the mechanism: `renders the error state when OCR fails`, not `test handle error`. A test whose assertion would pass against the unfixed code is not a test.

## Pull request size

Aim for 300–600 lines of diff. Split bigger work into a stack of PRs that each make sense on their own, and say in each description where it sits in the stack.

## Before writing code

- **Read the documentation.** Before relying on how a library's attribute
  is accessed, what it returns or which exceptions it raises, check its
  documentation for the version we pin. If the docs site blocks you, read
  the installed source (`site-packages`, `node_modules`) instead. Don't
  guess.
- **Look for how we already do it.** Search this repo for the same problem
  solved elsewhere and follow that pattern. Check our other repos too
  (github.com/MuckRock): muckrock, documentcloud, squarelet and the client
  libraries may already have a simple fix.
- **Use the library instead of rewriting it.** If a dependency or one of
  our client libraries (python-muckrock, python-documentcloud,
  python-squarelet) already does the job, use it rather than hand-rolling
  HTTP calls, token handling or retries. Ask before adding a new
  dependency.
- **Stay at the level you're working at.** If our code uses `requests`,
  debug at `requests`, not in `urllib3`. A mismatch between a library and
  its own dependencies is usually fixed by upgrading the library we use,
  not by patching around it.
- **Check before you disagree.** When someone says code or a claim is
  wrong, read the source or docs that settle it before answering, and say
  what you checked. If you were wrong, say so.

<!-- /AGENTS.md shared standard -->

## Running things

`inv test --path "squarelet -q -p no:sugar"` - add `--create-db` when the
schema has moved. `inv pylint` for lint, `inv format` for black and isort;
CI checks both. `inv test-stripe` runs the sandbox suite against real
Stripe and is required before any release that touches it.
