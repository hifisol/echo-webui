# Playbook: Graylog

**Version:** 0.1  |  **Last updated:** 2026-10-21  |  **Host:** Docker Compose stack on a Debian 12 VM (`rtms-dev`, VLAN 198), deployed by the `graylog` role in `hifi-client-deploy`
**Tool versions:** Graylog 6.0, MongoDB 6.0, OpenSearch 2.11.1 (from the role defaults, VERIFY running images with `docker compose images`). Docker from Docker's own apt repo (`docker-ce`), not the Debian package.

## Purpose
Central log search and routing: receive GELF messages, index them, and route them through streams and pipelines to dashboards and alerts. Use it when a log source needs a search home that is separate from the Wazuh indexer.

## Scope and Rules
- Ingest logs only from systems you own or are authorized to monitor.
- The GUI is for administrators. Reach it through the approved access path only (SSH tunnel or the Twingate or SSO route). Do not publish port 9000 to the internet or to a wider network. VERIFY the current access path, since it changed in October 2026.
- The GELF UDP input is exposed on the LAN for the log shippers. Keep it limited to the LAN and document each sender.
- Never store the root password hash, the password secret, or the admin password in this playbook, the repo, or notes. Keep them in the Ansible vault.
- Do not commit exported logs, dashboards with real data, or screenshots of production content.

## Tool Roles
| Tool | Role in this workflow | Not used for |
|---|---|---|
| Graylog 6.0 | Input handling, streams, pipelines, search UI, alert conditions | Long-term archive (set retention deliberately) |
| OpenSearch 2.11.1 | Index storage and search backend | Direct admin UI (use Graylog) |
| MongoDB 6.0 | Graylog configuration storage (inputs, streams, users) | Log storage |
| Docker Compose | Runs the three containers and their networks | Config management (that is Ansible) |
| Ansible (`hifi-client-deploy`, `graylog` role) | Builds and updates the stack | Day-to-day stream and pipeline edits |

## Pre-flight Checklist
- [ ] Authorization and scope confirmed
- [ ] Containers running (`docker compose ps` in `/opt/graylog`)
- [ ] Disk headroom checked (`df -h`), including the OpenSearch and Graylog journal volumes
- [ ] RAM headroom checked: OpenSearch is set to 2 GB heap, so the VM needs room beyond that
- [ ] The Ansible vault password is available for redeploys
- [ ] Sender list for the GELF input is current

## Phases

### Phase 1: Stack health
Goal: confirm all three containers are up and the API responds before touching config.

```bash
cd /opt/graylog
sudo docker compose ps
sudo docker logs --tail 50 graylog
```

Expected: `mongodb`, `opensearch`, and `graylog` are running. Graylog logs show it started without a `data_dir` or journal error.

### Phase 2: Access and login
Goal: reach the UI by the approved path.

1. Use the current access path (VERIFY: SSH tunnel through the jump host, or the SSO front end on port 9000 added in October 2026).
2. Log in as an administrator. Store the credentials in the password manager or vault, never in this file.
3. Create named accounts for each operator and leave the root account for break-glass use only.

### Phase 3: Inputs (receive logs)
Goal: confirm the GELF UDP input receives messages.

1. In the UI, open **System > Inputs** and confirm the GELF UDP input is **running**. VERIFY the menu path on Graylog 6.0.
2. Check the input's listen address and port (UDP 12201 on the LAN address, per the compose template). Do not change the bind address to a public interface.
3. Send one test message from an authorized host and confirm it appears under **Search**. Use a harmless test string.

Expected: the test message appears within about a minute.

### Phase 4: Streams and pipelines (routing)
Goal: separate incoming logs and transform them before indexing.

1. Create one stream per source type or per trust zone. Each stream should have one clear rule.
2. Add a pipeline only when a rule needs parsing. Test each pipeline rule on sample messages before connecting it to a live stream. VERIFY the pipeline test feature on 6.0.
3. Keep the rule and stream names in the engagement notes or the Ansible config, so a rebuild reproduces them.

### Phase 5: Dashboards and alerts
Goal: make the data useful without flooding the operator.

1. Build dashboards from saved searches. Keep time ranges explicit.
2. Alert only on conditions that need a human. Start with one alert per source and tune from there.
3. Record each alert's purpose and owner.

### Phase 6: Maintenance and redeploy
Goal: keep the stack current without losing data.

- Redeploy through Ansible, not by hand-editing `/opt/graylog` on the host. The `graylog` role is the source of truth.
- Before an upgrade, back up MongoDB and check the OpenSearch version pairing with the Graylog release notes. VERIFY the compatibility matrix for the target release.
- Restart with `docker compose` only when the Ansible run cannot do it. Use `state: restarted` in Ansible tasks for `community.docker.docker_compose_v2`.

## Quick Commands
```bash
cd /opt/graylog
sudo docker compose ps
sudo docker compose logs --tail 100 graylog
sudo docker compose logs --tail 100 opensearch

# Resource check
free -h
df -h /opt/graylog

# Redeploy the role (run from the hifi-client-deploy repo)
ansible-playbook rtms.yml --tags graylog
```

## Troubleshooting
| Symptom | Likely cause | Fix |
|---|---|---|
| Graylog exits with `Required parameter "data_dir" not found` | Graylog 6.0 needs `data_dir` in the config | Add `data_dir = /usr/share/graylog/data` to `graylog.conf.j2` and redeploy |
| `Fatal glibc error: CPU does not support x86-64-v2` or MongoDB AVX warning | Proxmox default CPU type (`kvm64`) hides AVX | On the Proxmox host, set `qm set <VMID> --cpu host`, then fully stop and start the VM (a reboot alone may not apply it) |
| `docker-compose-plugin` not found during install | Debian 12 apt has no compose plugin | Install from Docker's official apt repo, as the role does |
| Ansible task fails on `restarted` | Wrong parameter for `docker_compose_v2` | Use `state: restarted` |
| No messages in search | Input not running, wrong port, or firewall | Check the input status, then test UDP 12201 from the sender |
| OpenSearch will not start | Memory lock or heap too large for the VM | Check `bootstrap.memory_lock` and the 2 GB heap against the VM RAM |
| Disk fills | Retention too long or journal not capped | Set index retention and check the journal directory |

## Change Log
- v0.1 2026-10-21: initial draft from the `graylog` role, the rtms-dev deployment notes, and the role defaults
