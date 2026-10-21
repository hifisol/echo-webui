# Playbooks

Repeatable, step-by-step workflows for each appliance in the RPTR stack. Each playbook answers one question: "I have this appliance and this job to do, what is the most efficient way to run it?"

## Index

| Appliance / Stack | Playbook | Status |
|---|---|---|
| GVM + Nuclei + Burp Suite + Caido (Debian 12 VM) | [gvm-nuclei-burp-caido.md](gvm-nuclei-burp-caido.md) | Draft v0.1 |
| MISP threat intel appliance | [misp.md](misp.md) | Draft v0.1 |
| Wazuh | [wazuh.md](wazuh.md) | Draft v0.1 |
| Graylog | [graylog.md](graylog.md) | Draft v0.1 |

Add a row here whenever a new playbook is created.

## Conventions

- One playbook per appliance or per tool stack. Copy `_TEMPLATE.md` to start.
- File names are lowercase, hyphenated, and list the tools: `wazuh-graylog.md`, `misp.md`.
- Every playbook has the same sections: Purpose, Scope and Rules, Tool Roles, Pre-flight, Phases, Quick Commands, Troubleshooting, Change Log.
- Commands must be copy-pasteable. Use `<PLACEHOLDERS>` in angle brackets for values that change.
- Never commit credentials, API keys, scan results, or client data. Keep engagement output outside the repo.
- Only run scanning and testing tools against systems you own or have written authorization to test.
- Bump the version and add a Change Log line whenever a playbook changes.

## Suggested engagement output layout (kept outside the repo)

```
~/engagements/<CLIENT_OR_LAB>/<YYYY-MM-DD>/
  scope/        targets.txt, rules-of-engagement notes
  discovery/    ports, live hosts
  gvm/          report exports (PDF, XML)
  nuclei/       jsonl results, markdown export
  proxy/        Burp project, Caido project, evidence screenshots
  report/       final write-up
```
