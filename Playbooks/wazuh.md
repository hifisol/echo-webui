# Playbook: Wazuh Manager

**Version:** 0.1  |  **Last updated:** 2026-10-21  |  **Host:** Wazuh manager `prm-nxs-1`
**Tool versions:** Wazuh 4.14.9 (verified 2026-10-21 with `wazuh-control info`). Indexer, dashboard, and Filebeat versions: VERIFY.

## Purpose
Run the day-to-day work on the Wazuh manager: keep agents connected, load custom rules and decoders safely, triage alerts, and confirm alerts are still flowing after a reboot or change.

## Scope and Rules
- Monitor only systems you own or are authorized to monitor.
- Custom rules live in the `wazuh-config` backup repo and are copied to the manager. Edit the repo first, then deploy, so the manager does not drift from the backup.
- Use level 0 rules to suppress known-good noise. Scope each suppression to a host or a field, never to a broad pattern.
- Test every rule change with `wazuh-logtest` before restarting the manager.
- Do not copy alert data, agent keys, or indexer passwords into the repo or into notes.

## Tool Roles
| Tool | Role in this workflow | Not used for |
|---|---|---|
| Wazuh manager (`wazuh-manager`) | Rule engine, agent management, alert generation | Long-term search (that is the indexer) |
| Wazuh indexer and dashboard | Alert search, dashboards, investigation | Rule logic (it reads what the manager writes) |
| `wazuh-logtest` | Offline test of decoders and rules against a sample log line | Live monitoring |
| `agent_control` | Agent status and enrollment checks | Rule changes |
| `wazuh-config` repo | Source of truth for custom rules, decoders, and active response | Runtime state |

## Pre-flight Checklist
- [ ] Authorization and scope confirmed
- [ ] Manager services healthy (Quick Commands)
- [ ] Disk headroom checked (`df -h /var/ossec`)
- [ ] Rule ID range checked against the allocation table below before adding a rule
- [ ] Current `local_rules.xml` backed up or in version control
- [ ] Change window chosen (manager restarts drop agent events briefly)

## Phases

### Phase 1: Health and agent check (after a reboot or outage first)
Goal: confirm the stack is up and alerts are flowing before any tuning.

```bash
sudo systemctl is-active wazuh-manager wazuh-indexer wazuh-dashboard filebeat rsyslog
systemctl list-units --type=service --state=failed --no-pager
sudo /var/ossec/bin/agent_control -ls
sudo find /var/ossec/logs/alerts -name "alerts.json" -mmin -5 -exec ls -la {} \;
```

Expected: services active, expected agents shown as Active, and `alerts.json` modified in the last 5 minutes.

Boot-time race: `wazuh-manager` can show `failed` after boot even though the daemons are running. The indexer was not ready when the manager started. If the daemons are up and agents are Active, do a clean restart instead of a reload. A reload does nothing against a unit that systemd marks inactive.

```bash
sudo systemctl stop wazuh-manager
sleep 5
sudo systemctl start wazuh-manager
```

### Phase 2: Write and test a rule or decoder
Goal: change detection logic without breaking the manager.

1. Pick an ID from the allocation table. Custom rules use IDs 100000 and up. Check that the ID is free:
   ```bash
   sudo grep -rn 'id="<RULE_ID>"' /var/ossec/etc/rules/ /var/ossec/etc/decoders/
   ```
2. Write the rule in the `wazuh-config` repo, not on the manager. For a whitelist, use `level="0"`, set `<if_sid>` to the parent rule, and limit the match with `<hostname>` or a `<field>` where possible.
3. Copy the file to the manager, then test with `wazuh-logtest` using a real sample line from `alerts.json`. Confirm the expected rule ID fires, or that the suppression rule wins.
4. Check the configuration before restarting (VERIFY the exact test flag for this version with `/var/ossec/bin/wazuh-analysisd -t` or `wazuh-control` help).
5. Restart the manager (Phase 1 method if the unit is in a failed state), then watch `ossec.log` for errors.

```bash
sudo /var/ossec/bin/wazuh-logtest
sudo tail -50 /var/ossec/logs/ossec.log
```

### Phase 3: Alert triage
Goal: decide which alerts are real.

1. Start from the dashboard or from `alerts.json` for the time window. Filter by rule level and group.
2. For each alert: confirm the agent, the user, the process, and the time. Compare with the host's known activity (patching, scheduled jobs, backups).
3. Known benign patterns in this environment belong in a scoped whitelist with a description that explains why, so the next reviewer can see it.
4. Escalate anything you cannot explain. Keep the evidence in the engagement notes.

### Phase 4: Feed-driven rules (MISP and IOC lists)
Goal: keep CDB-list rules current.

- MISP-sourced CDB lists and rules 100500-100515 are covered in [misp.md](misp.md). Do not edit `misp_rules.xml` on the manager.
- Any new list lives under `/var/ossec/etc/lists/` and needs a matching rule in the repo.

### Phase 5: Confirm the manager is still healthy
Goal: end each change with proof, not assumption.

```bash
sudo /var/ossec/bin/wazuh-control info
sudo /var/ossec/bin/agent_control -ls | head -20
sudo tail -3 /var/ossec/logs/alerts/alerts.json | cut -c1-300
```

## Quick Commands
```bash
# Version
sudo /var/ossec/bin/wazuh-control info

# Restart the manager after a rule change
sudo systemctl restart wazuh-manager

# Restart the indexer (only if needed)
sudo systemctl restart wazuh-indexer
sudo systemctl status wazuh-indexer

# Local rules and whitelist location
sudo less /var/ossec/etc/rules/local_rules.xml

# Live alerts
sudo tail -f /var/ossec/logs/alerts/alerts.json
```

## Rule ID Allocation
From the `wazuh-config` README. Check it before adding a rule.

| Range | Purpose | File |
|---|---|---|
| 95000-95005 | Ares CVE enrichment | `ares-cve_rules.xml` |
| 100001-100036 | Windows and Linux whitelists | `local_rules.xml` |
| 100100-100199 | UniFi and UDM Pro | `local_rules.xml` |
| 100200-100271 | RITA detection and whitelists | `rita_rules.xml` |
| 100300-100607 | Zeek IDS, DNS bypass, domain intel | `zeek_rules.xml` |
| 100400-100421 | ESPHome and Tasmota IoT | `esphome_rules.xml` |
| 100500-100515 | MISP threat intelligence | `misp_rules.xml` |
| 100700-100860 | Advanced and Iranian APT detection | `local_rules.xml` |
| 100900-100920 | GreenBlood ransomware and YARA | `greenblood_rules.xml` |

## Troubleshooting
| Symptom | Likely cause | Fix |
|---|---|---|
| `wazuh-manager` shows failed but agents are Active | Boot-time race with the indexer | Clean stop and start (Phase 1) |
| Rule change has no effect | File not copied, wrong file, or no restart | Confirm the file on the manager, run `wazuh-logtest`, restart |
| Rule fires on everything | Missing `<hostname>` or `<field>` scope, or wrong `if_sid` | Narrow the match and retest with `wazuh-logtest` |
| No new alerts in `alerts.json` | Manager down, or agents disconnected | Phase 1 checks, then `agent_control -ls` |
| Dashboard shows errors but manager is healthy | Indexer or dashboard issue, not the manager | Check the indexer service and its logs (VERIFY log path) |
| Config change lost after redeploy | Edit made on the manager only | Move the change into the `wazuh-config` repo and redeploy |

## Change Log
- v0.1 2026-10-21: initial draft from the `wazuh-config` README, the Wazuh quick reference, and the 4.14.9 version check
