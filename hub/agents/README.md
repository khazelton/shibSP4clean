# Hub agent list (generated agent beans)

A stand-in for the hybrid "loader bean" Scott described on the dev list (2026-11-03): advanced configuration stays in hub XML as a mostly one-time cost, and the day-to-day agent entries live in a flat file.

| File | Role | Edited |
|---|---|---|
| `agents.csv` | one row per agent: `agent_id,group,allowed_ranges,usernames,owner` (lists space-separated) | day to day, or by an IGA tool |
| `templates/<group>.xml` | bean template shared by a group of agents (`${id}`, `${usernames_attr}`, `${ranges}`, `${comment}`, `${owner}`) | once per kind of agent |
| `generated/agents-generated.xml` | output of `../../gen-agents-xml.py`; committed so a fresh clone starts | never by hand |
| `../conf/agents.xml` | static half: RP overrides, credential import | rarely |

Workflow: edit `agents.csv`, then run `./gen-agents-xml.py --reload` from `deploy/`. The generator validates, writes the file atomically, and reloads the hub's `AgentResolverService`; there's no rebuild or restart. Without `--reload`, the hub picks the change up within `sp.service.agents.checkInterval` (5 minutes). `--check` exits 1 if the generated file is out of date.

Validation: ids and usernames must be safe names; a username may belong to only one agent, because the hub resolves the agent *from* the presented username. With no usernames, the agent id is the username. Ranges must parse as CIDR, and an empty range list is rejected. The group must have a template. The report shows where each username's credential is expected (`htpasswd` if it's in `../htpasswd/agents.htpasswd`, otherwise LDAP). It doesn't query LDAP.

Hub wiring: `hub/entrypoint.sh` defines `shibboleth.sp.AgentResolverResources` in `global.xml` with both `conf/sp/agents.xml` and `conditional:conf/sp/generated/agents-generated.xml`. Defining that bean replaces the plugin's default list. `compose.yaml` bind-mounts `generated/` read-only.
