#!/usr/bin/env bash
# Issues/rotates the secret for one agent service account and delivers it to both ends,
# the way an IGA/secret-management tool would:
#   credential store <- the account's password, either
#                         LDAP:     password of <username> in the ldap container (default), or
#                         htpasswd: $apr1$ hash line in hub/htpasswd/agents.htpasswd (--htpasswd)
#   agent            <- agent/conf/shibboleth-sp/agent.pwd (agent.ini secretFile)
# The hub sees nothing: no restart, no env var. It validates against LDAP live and re-reads
# the htpasswd file when its modification time changes.
#
#   ./gen-agent-secret.sh                            # LDAP account sa1-sp4-agent
#   ./gen-agent-secret.sh sa2-sp4-agent              # LDAP: rotate onto the second account
#   ./gen-agent-secret.sh --htpasswd sa3-sp4-agent   # flat file: no directory involved
#
# The username must be in the hub agent's p:usernames (hub/conf/agents.xml). After rotating,
# point agent.ini [remoting] agentID at <username> and recreate the agent only (--no-deps
# keeps compose from re-evaluating the hub):
#   docker compose up -d --no-deps --force-recreate agent
set -euo pipefail
cd "$(dirname "$0")"

MODE=ldap
if [ "${1:-}" = "--htpasswd" ]; then MODE=htpasswd; shift; fi
USERNAME=${1:-sa1-sp4-agent}
SECRET=$(openssl rand -base64 36 | tr -d '\n/+=' | cut -c1-40)

if [ "$MODE" = htpasswd ]; then
  HTFILE=hub/htpasswd/agents.htpasswd
  mkdir -p "$(dirname "$HTFILE")"
  touch "$HTFILE"
  HASH=$(printf '%s' "$SECRET" | openssl passwd -apr1 -stdin)
  # replace this user's line (or append), then swap the file in atomically; the hub
  # bind-mounts the directory, so the new inode is picked up
  TMP=$(mktemp "$HTFILE.XXXXXX")
  { grep -v "^${USERNAME}:" "$HTFILE" || true; printf '%s:%s\n' "$USERNAME" "$HASH"; } > "$TMP"
  chmod 644 "$TMP"   # hashes only; the hub's Jetty user must be able to read it
  mv "$TMP" "$HTFILE"
  echo "htpasswd entry written for ${USERNAME} in deploy/${HTFILE}"
else
  if docker compose ps --status running ldap >/dev/null 2>&1 && [ -n "$(docker compose ps -q ldap)" ]; then
    ADMIN_PW=$(grep -E '^LDAP_ADMIN_PASSWORD=' .env | cut -d= -f2- || true)
    docker compose exec -T ldap /app/lldap_set_password \
      --base-url http://localhost:17170 \
      --admin-username admin --admin-password "${ADMIN_PW:-poc-admin-password}" \
      --username "$USERNAME" --password "$SECRET" >/dev/null
    echo "LDAP password set for ${USERNAME}"
  else
    echo "ldap container not running; LDAP password NOT set (run ./ldap-seed.sh then re-run)" >&2
    exit 1
  fi
fi

printf '%s' "$SECRET" > agent/conf/shibboleth-sp/agent.pwd
chmod 600 agent/conf/shibboleth-sp/agent.pwd
echo "secret (${#SECRET} chars) written to agent/conf/shibboleth-sp/agent.pwd"
echo "agent.ini [remoting] agentID must be: ${USERNAME}"
