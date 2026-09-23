# Issue tracker: GitHub

Issues and specs live in GitHub Issues for `avsngh-git/RAGpipeline`.
Use the `gh` CLI from this repository.

## Operations

- Create: `gh issue create --title "..." --body-file <file>`
- Read: `gh issue view <number> --comments`
- List: `gh issue list --state open --json number,title,body,labels`
- Comment: `gh issue comment <number> --body-file <file>`
- Label: `gh issue edit <number> --add-label "<label>"`
- Remove a label: `gh issue edit <number> --remove-label "<label>"`
- Close: `gh issue close <number> --comment "..."`

When a skill says "publish to the issue tracker", create a GitHub issue.
When it says "fetch the relevant ticket", read the issue and its comments.

Plans and tickets must follow the project source of truth referenced in
`AGENTS.md`. Identify the delivery phase and relevant requirements.

## Pull requests as a triage surface

PRs as a request surface: no.

## Wayfinding

Use an issue labelled `wayfinder:map` for Notes, Decisions-so-far, and Fog.
Link child tickets as GitHub sub-issues, or use a task list in the map and
a `Part of #<map>` reference in each child.

Label children `wayfinder:<type>` using research, prototype, grilling, or task.
Record blockers with native issue dependencies when available; otherwise use
a `Blocked by: #<number>` line.

Select the first open, unassigned child in map order with no open blockers.
Claim it with `gh issue edit <number> --add-assignee @me`.
On resolution, comment with the result, close the ticket, and update the map's
Decisions-so-far with a summary and link.
