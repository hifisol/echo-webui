# Playbook: GVM + Nuclei + Burp Suite + Caido

**Version:** 0.1  |  **Last updated:** 2026-10-19  |  **Host:** Debian 12 VM (GVM community build)
**Tool versions:** VERIFY. Not checked against the host from this workspace. Record `gvmd --version`, `nuclei -version`, and the Burp and Caido versions on the first run.

## Purpose
Run a layered vulnerability assessment from one VM: GVM for network and host vulnerabilities, Nuclei for fast web and CVE checks, and Burp Suite or Caido for manual validation of anything worth a closer look.

## Scope and Rules
- Scan only systems you own or have written authorization to test. Keep the scope file with the engagement notes.
- Do not run a GVM scan, a large Nuclei run, and Burp's scanner at the same time. They compete for CPU and RAM on this VM.
- Throttle against production or fragile targets (see the rate limits in Phase 3).
- Store results outside any git repo. Never commit scan output or credentials.

## Tool Roles
| Tool | Role in this workflow | Not used for |
|---|---|---|
| GVM (OpenVAS) | Scheduled infrastructure scans, authenticated checks, patch and config findings, management-ready reports | Fast checks on web apps, custom one-off checks |
| Nuclei | Quick CVE checks, misconfigurations, exposed panels, default logins, takeovers, new-CVE sweeps | Deep host patch auditing, authenticated OS scans |
| Burp Suite | Manual testing, replaying and tweaking Nuclei hits, evidence capture | Bulk scanning of many hosts |
| Caido | Lightweight alternative to Burp for replay and review, second opinion | Same as Burp |
| httpx / naabu (optional) | Discovery that feeds Nuclei a clean list of live web targets | Vulnerability detection |

## Pre-flight Checklist
- [ ] Authorization and scope confirmed, `targets.txt` written
- [ ] GVM services healthy (see Quick Commands)
- [ ] GVM feed synced and Nuclei templates updated
- [ ] Burp and Caido on different proxy ports (Burp 8080, Caido 8081)
- [ ] Disk headroom checked (`df -h`)
- [ ] Engagement directory created

```bash
mkdir -p ~/engagements/<NAME>/$(date +%F)/{scope,discovery,gvm,nuclei,proxy,report}
cd ~/engagements/<NAME>/$(date +%F)
```

## Phase 0: Update everything
```bash
# GVM feed (service and user names can vary by install method)
sudo -u _gvm greenbone-feed-sync      # or: sudo greenbone-feed-sync
sudo gvm-check-setup

# Nuclei templates
nuclei -update-templates
nuclei -version
```
Let the GVM feed load fully before scanning. After a sync, the scanner can take several minutes to ingest it.

## Phase 1: Discovery (build the target lists)
Goal: know which hosts are alive, which ports are open, and which of those speak HTTP(S).

```bash
# Ports (naabu), or use nmap if you prefer
naabu -list scope/targets.txt -top-ports 1000 -rate 500 -o discovery/ports.txt

# Alternative with service versions
nmap -sV -T3 -iL scope/targets.txt -oA discovery/nmap

# Live web targets for Nuclei (httpx)
httpx -l discovery/ports.txt -title -tech-detect -status-code -o discovery/live-web.txt
```
Output to carry forward: `targets.txt` goes to GVM, `live-web.txt` goes to Nuclei.

## Phase 2: Infrastructure scan with GVM
Goal: network, OS, and service vulnerabilities, ideally authenticated.

1. In GSA, create a **Target** from `scope/targets.txt`. Pick the port list that matches Phase 1.
2. Add **Credentials** (SSH, SMB, or WinRM) for authenticated scans. Authenticated results are far more accurate for patch and config issues.
3. Create a **Task** using the **Full and fast** scan config. Schedule it off-hours if the targets are production.
4. Run it, then review results with the default **QoD (quality of detection) threshold of 70%** to cut noise. Lower it only when hunting.
5. Export the report (PDF for humans, XML for archives) into `gvm/`.

Tips:
- Run one GVM task at a time on this VM.
- Re-run the same task later and use the **delta report** to show what changed.
- For automation, use `gvm-cli` / `gvm-tools` over the gvmd socket.

## Phase 3: Web and CVE sweep with Nuclei
Goal: fast, targeted checks against web-facing assets. Run in tiers, cheapest first.

```bash
# Tier A: high-impact triage
nuclei -l discovery/live-web.txt -severity critical,high \
  -rl 50 -c 15 -etags dos,fuzz -jsonl -o nuclei/tier-a.jsonl

# Tier B: new templates only (great right after an update or a fresh CVE)
nuclei -l discovery/live-web.txt -nt -rl 50 -c 15 -jsonl -o nuclei/tier-b-new.jsonl

# Tier C: misconfigurations and exposures
nuclei -l discovery/live-web.txt -tags misconfig,exposure,default-login,takeover,panel \
  -rl 30 -c 10 -jsonl -o nuclei/tier-c.jsonl

# Optional: technology-aware automatic scan
nuclei -l discovery/live-web.txt -as -rl 30 -c 10 -jsonl -o nuclei/auto.jsonl
```

Gentler settings for fragile or production targets: `-rl 10 -c 5 -timeout 10 -retries 1`.

Quick triage view of any results file:
```bash
jq -r '[.info.severity, .["template-id"], .host, .["matched-at"]] | @tsv' nuclei/tier-a.jsonl | sort
```

Markdown export for notes or hand-off: add `-me nuclei/md/`.

## Phase 4: Manual validation with Burp or Caido
Goal: confirm that each Nuclei and GVM finding is real, and capture evidence.

1. Re-send the interesting request through your proxy so you can see exactly what the template did:
   ```bash
   # Burp on 8080
   nuclei -u https://<TARGET> -id <TEMPLATE-ID> -proxy http://127.0.0.1:8080 -rl 5 -c 1

   # Caido on 8081
   nuclei -u https://<TARGET> -id <TEMPLATE-ID> -proxy http://127.0.0.1:8081 -rl 5 -c 1
   ```
2. Send the request to Repeater (Burp) or Replay (Caido). Confirm the response proves the issue, not just that a string matched.
3. Try to reproduce by hand. If it does not reproduce, mark it as a false positive and note why.
4. Save evidence: request, response, timestamp, and a screenshot into `proxy/`.
5. Keep one tool as the system of record per engagement so evidence is not split.

## Phase 5: Triage and reporting
1. Combine the sources into one findings sheet: ID, host, source (GVM or Nuclei), severity, status (confirmed, false positive, needs retest), evidence link, remediation.
2. De-duplicate. GVM and Nuclei often flag the same CVE on the same host.
3. Prioritize by confirmed exploitability and exposure, then by CVSS.
4. Reporting options:
   - GVM PDF for the infrastructure section.
   - Nuclei JSONL or Markdown for the web section.
   - **DefectDojo** if you want one place to import both (it has parsers for OpenVAS and Nuclei) with de-duplication and tracking.
5. Archive the engagement directory and record the tool and template versions used.

## Quick Commands
```bash
# GVM health
sudo gvm-check-setup
sudo systemctl status gvmd ospd-openvas gsad   # names vary by install

# Nuclei
nuclei -tl | head                      # list templates
nuclei -tgl                            # list tags
nuclei -u https://<TARGET> -tags cve -severity critical,high
nuclei -l live-web.txt -H "Authorization: Bearer <TOKEN>"   # authenticated web scan
nuclei -validate -t <custom-template>.yaml                  # test a custom template

# Resources
htop
df -h
```

## Troubleshooting
| Symptom | Likely cause | Fix |
|---|---|---|
| Burp or Caido will not start the proxy | Both trying to use port 8080 | Set Caido to 8081 (or any free port) |
| GVM scan stalls or is very slow | Feed still loading, or VM is out of RAM or CPU | Wait for feed ingestion, stop Burp or Nuclei runs, add RAM |
| Nuclei is slow or targets time out | Rate too high, WAF throttling | Lower `-rl` and `-c`, raise `-timeout` |
| Nuclei results flood with low-value hits | Info-level templates included | Add `-severity medium,high,critical` |
| Nuclei findings not in GVM reports | No native importer | Use DefectDojo or merge manually (by design) |
| GVM results look sparse | Unauthenticated scan | Add credentials to the target |
| Disk filling up | Feed, templates, and Burp project files | Clean old projects and reports, expand the VM disk |

## Change Log
- v0.1 2026-10-19: initial draft
