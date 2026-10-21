# Playbook: MISP Threat Intel Appliance

**Version:** 0.1  |  **Last updated:** 2026-10-21  |  **Host:** MISP deployed by `misp-deploy` (Ansible, LXC + Docker on the Proxmox host). Export consumer runs on the Wazuh manager (nxs-1).
**Tool versions:** MISP API reported v2.5.32 (2026-02-27 session, VERIFY current version on the host). Wazuh manager 4.14.9 (verified 2026-10-21).

## Purpose
Keep MISP feeds fresh, filter out noisy indicators, and export the result to Wazuh as CDB lists so that alerts match known-bad IPs, domains, URLs, and hashes (rules 100500-100515). Use it for routine feed upkeep and for retro-hunting past alerts against current intel.

## Scope and Rules
- Use feeds and indicators only for defensive monitoring and investigation of systems you own or are authorized to monitor.
- Never put the MISP API key in a script, a commit, or a notes file. Keep it in the Ansible vault (`misp-deploy/ansible/inventory/group_vars`) or an environment variable at run time.
- Enable warninglists before exporting IOCs to Wazuh. Without them, CDN and cloud IPs produce false positives.
- Do not edit `misp_rules.xml` on the manager. The file is managed by Ansible and is overwritten on the next deploy.
- Keep exported lists and correlation output outside the repo.

## Tool Roles
| Tool | Role in this workflow | Not used for |
|---|---|---|
| MISP | Feed aggregation, IOC storage, warninglist filtering, source of truth for indicators | Real-time alert matching, log search |
| `cdb-sync-misp.py` (on nxs-1, `/opt/`) | Exports MISP attributes to Wazuh CDB lists on a schedule | Enriching one-off indicators |
| Wazuh manager (nxs-1) | Matches CDB lists against live events (rules 100500-100515) | Feed management |
| `misp-deploy/scripts/wazuh-misp-correlate.py` | Retro-hunt: extracts IOCs from 7 days of alerts and checks them against MISP and the CDB lists | Scheduled detection (it is a hunt script) |

## Pre-flight Checklist
- [ ] Authorization and scope confirmed
- [ ] MISP web UI and API reachable from your workstation (VERIFY the URL in the Ansible inventory, do not copy it into notes)
- [ ] Each enabled feed shows a recent successful fetch
- [ ] Warninglists enabled (see Phase 2)
- [ ] Disk headroom checked on MISP and on nxs-1 (`df -h`, `/var/ossec/etc/lists` and `/var/ossec/logs`)
- [ ] Ansible vault password available for any redeploy

## Phases

### Phase 1: Feed health (cheapest, do first)
Goal: confirm the feeds are current. Stale feeds give stale matches; in Feb 2026 the feeds were years old and a 7-day correlation returned zero matches.

1. In the MISP UI, open **Sync Actions > List Feeds** (VERIFY menu path on the installed version).
2. Confirm each enabled feed has a recent "last fetched" time and no error.
3. For any feed with errors, check the feed format. A MISP-format feed that requests `manifest.json` and gets a 404 is broken. Replace it with the CSV version of the same source.
4. Trigger a fetch on all feeds after changes, then wait for ingestion to finish before exporting.

Expected output: all enabled feeds fetched recently with no errors. Reference point from Feb 2026, after switching to CSV feeds: about 1,650 events and about 434,000 attributes from eight feeds (abuse.ch sources: MalwareBazaar, SSLBL, Feodo Tracker, ThreatFox CSV).

### Phase 2: Warninglists
Goal: suppress known-benign infrastructure before it reaches Wazuh.

1. In the MISP UI, open **Input Filters > Warninglists** (VERIFY on the installed version) and enable the cloud, CDN, search engine, and RFC1918 lists.
2. Lists enabled in Feb 2026 (25 total): Cloudflare, Akamai, Amazon AWS, Apple, Google, Microsoft Azure, Microsoft Office 365, Fastly, CrowdStrike, Zscaler, Cisco Umbrella Top 1M, Majestic Million, Tranco, University Domains, RFC1918, RFC5735, Multicast, Google GCP, Microsoft, Stackpath, Alibaba, DigitalOcean, OVH, Scaleway, Linode.
3. Verify with an API query that uses `enforceWarninglist=true`. Known CDN IPs should return no results.

Effect in Feb 2026: the export dropped from 74,305 IOCs to 65,700.

### Phase 3: Export to Wazuh CDB lists
Goal: refresh the Wazuh lists from MISP.

- The sync script is `/opt/cdb-sync-misp.py` on nxs-1 with config `/opt/cdb-sync-misp.conf`. Cron runs it on the schedule set by `misp_cdb_sync_interval` in the `wazuh-misp` role.
- Lists are written to `/var/ossec/etc/lists/`: `misp-ip`, `misp-domain`, `misp-hostname`, `misp-url`, `misp-md5`, `misp-sha256`. VERIFY whether `misp-sha1` is exported; the correlation script expects it.
- Log: `/var/log/cdb-sync-misp.log`.

Expected: the log shows a successful run, and the list files have a recent modification time. Feb 2026 counts for reference: `misp-ip` about 18,000 entries, `misp-domain` about 19,400.

```bash
sudo tail -20 /var/log/cdb-sync-misp.log
sudo ls -la /var/ossec/etc/lists/
```

VERIFY whether the manager must be restarted for updated CDB lists to load. The Feb 2026 session did not record this.

### Phase 4: Confirm the Wazuh rules fire
Goal: prove the lists and rules work before trusting them.

- Rules are in `misp_rules.xml` (IDs 100500-100515): 100500 and 100501 match source and destination IP on `misp-ip`, 100502 matches hostname on `misp-domain`, and 100503 matches URL on `misp-url`. Level 10.
- Test with `wazuh-logtest` and a sample log line that contains an IP known to be in `misp-ip` (pick one from the list file). Do not use a real client address in shared notes.

```bash
sudo /var/ossec/bin/wazuh-logtest
```

Expected: the event is decoded and rule 100500 (or 100501) fires. If it does not, check the field name and the list path.

### Phase 5: Retro-hunt the last 7 days of alerts
Goal: find past alerts whose indicators match current intel, then triage them.

1. The correlation script reads the live `alerts.json` and yesterday's gzipped archive, extracts external IPs, domains, and hashes, and checks each against MISP with a rate limit.
2. **VERIFY before use:** the script currently hardcodes the MISP URL, the API key, and the output path (`/tmp`). Move these to environment variables and an engagement directory before running it again.
3. Triage each match:
   - CDN or cloud IPs usually mean a missing warninglist (Phase 2). Fix the list rather than closing the match by hand.
   - Search engines and analytics endpoints are often false positives. Feb 2026 examples: a CDN IP tagged with a CVE, and a search engine IP tagged with a malware event.
   - Confirm any remaining match against the raw alert and the host's activity before escalating.
4. Record the verdicts in the engagement notes, not in the repo.

### Phase 6: Feed back to MISP
Goal: keep MISP from repeating false positives.

- Record confirmed false positives so the warninglists and the feed sources stay accurate. VERIFY the MISP feature used for this (false-positive tagging or a local warninglist entry) on the installed version.

## Quick Commands
```bash
# Export state on the Wazuh side
sudo tail -20 /var/log/cdb-sync-misp.log
sudo ls -la /var/ossec/etc/lists/

# Manual export run (lists are rewritten; run in a quiet window)
sudo /usr/bin/python3 /opt/cdb-sync-misp.py --config /opt/cdb-sync-misp.conf

# Rule test
sudo /var/ossec/bin/wazuh-logtest

# Wazuh version and status
sudo /var/ossec/bin/wazuh-control info
```

## Troubleshooting
| Symptom | Likely cause | Fix |
|---|---|---|
| Feed errors with 404 on `manifest.json` | MISP-format feed pointed at a source that publishes CSV | Delete it and add the CSV feed for the same source |
| Correlation returns zero matches | Feeds are stale | Phase 1: fetch all feeds, then re-export |
| Many CDN or cloud matches | Warninglists disabled | Phase 2: enable the cloud and CDN lists, re-export |
| CDB lists not updating | Cron job or sync script failing | Read `/var/log/cdb-sync-misp.log`, run the sync manually |
| Rule 100500 never fires | List missing, wrong field, or lists not loaded | Phase 4: check the list file, test with `wazuh-logtest` |
| Lists are overwritten after a change | Changes made on nxs-1 instead of in Ansible | Make the change in `misp-deploy` and redeploy the `wazuh-misp` role |
| Correlation script fails or hangs | MISP API timeout or rate limit | Raise the timeout, keep the 0.3 s pause between calls |

## Change Log
- v0.1 2026-10-21: initial draft from the 2026-02-27 MISP session, the `misp-deploy` roles, and the `wazuh-config` rule allocation
