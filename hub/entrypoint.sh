#!/usr/bin/env bash
# Applies PoC config to the hub at container start, then runs Jetty in the foreground.
# Idempotent: every edit is a "set or replace" so restarts are safe.
set -euo pipefail
cd "${IDP_HOME}"

: "${GOOGLE_CLIENT_ID:?GOOGLE_CLIENT_ID not set}"
: "${GOOGLE_CLIENT_SECRET:?GOOGLE_CLIENT_SECRET not set}"

# setprop FILE KEY VALUE  -- replace "key = ..." / "#key = ..." or append
setprop() {
  local f=$1 k=$2 v=$3
  if grep -qE "^#?\s*${k}\s*=" "$f"; then
    sed -i -E "s|^#?\s*${k}\s*=.*|${k} = ${v}|" "$f"
  else
    printf '\n%s = %s\n' "$k" "$v" >> "$f"
  fi
}

SP=conf/sp/sp.properties
OIDC=conf/sp/oidc.properties

# Identity leg: hub as OIDC RP against Google
setprop "$SP"   sp.issuer                         "${GOOGLE_CLIENT_ID}"
setprop "$SP"   sp.defaultAuthority               "https://accounts.google.com"
setprop "$OIDC" sp.oidc.defaultClientSecret       "${GOOGLE_CLIENT_SECRET}"
setprop "$OIDC" sp.oidc.acceptUnfilteredAttributes "true"        # PoC only; Phase 3 adds a filter
# Extra scopes beyond openid, else Google returns only "sub". Values are sent verbatim
# (verified: "PROFILE,EMAIL" went out literally), so use the lowercase OIDC scope names.
setprop "$OIDC" sp.oidc.scopes                    "profile,email"

# Phase 2: agents must authenticate (basic) and come from their declared address.
# The global range stays at the loopback default; each Agent bean in agents.xml
# carries its own allowedAddressRanges. The secret is referenced from agents.xml
# as %{poc.agent.secret}.
setprop "$SP"   sp.agent.authn.method   "basic"
setprop "$SP"   poc.agent.secret        "${AGENT_SECRET:-unset}"

# Phase 4: validate agent credentials against LDAP (service accounts), in addition to
# the in-config validator. Bean list must live in conf/global.xml (not agents.xml).
if [ -n "${AGENT_LDAP_URL:-}" ]; then
  setprop "$SP" sp.agent.authn.LDAP.authenticator "directAuthenticator"
  setprop "$SP" sp.agent.authn.LDAP.ldapURL       "${AGENT_LDAP_URL}"
  setprop "$SP" sp.agent.authn.LDAP.dnFormat      "${AGENT_LDAP_DNFORMAT:-uid=%s,ou=people,dc=localtest}"
  setprop "$SP" sp.agent.authn.LDAP.useStartTLS   "false"
  setprop "$SP" sp.agent.authn.LDAP.sslConfig     "jvmTrust"
fi

# Agent credential validators, documented form (SecuringAgentConnections), in conf/global.xml.
# Needs hub nightly 0.0.3-32 or later: before that these beans were flow-scoped and invisible
# here, and the LDAP factory lacked startTLSTimeout/autoReconnect/reconnectTimeout (defects #2, #3).
# Chain: internal (agents.xml secrets) -> LDAP (if AGENT_LDAP_URL) -> htpasswd (if AGENT_HTPASSWD).
# Written once per container; recreate the hub container after changing these env vars.
if ! grep -q 'shibboleth.sp.AgentValidators' conf/global.xml; then
  {
    echo '    <!-- SP hub: agent credential validators (PoC Phase 4). See hub/entrypoint.sh. -->'
    echo '    <util:list id="shibboleth.sp.AgentValidators">'
    echo '        <ref bean="shibboleth.sp.AgentSecretValidator" />'
    [ -n "${AGENT_LDAP_URL:-}" ] && echo '        <bean parent="shibboleth.sp.LDAPValidator" />'
    if [ -n "${AGENT_HTPASSWD:-}" ]; then
      if [ -f "${AGENT_HTPASSWD}" ]; then
        # $apr1$, {SHA} and crypt ($5$/$6$) hashes; bcrypt ($2y$, htpasswd -B) is not supported.
        echo "        <bean parent=\"shibboleth.sp.HTPasswdValidator\" p:resource=\"${AGENT_HTPASSWD}\" />"
      else
        echo "WARN: ${AGENT_HTPASSWD} missing; htpasswd validator not configured" >&2
      fi
    fi
    echo '    </util:list>'
    echo
    echo '</beans>'
  } > /tmp/validators.xml
  perl -0pi -e 'BEGIN{local $/; open F,"</tmp/validators.xml"; $r=<F>; close F} s|</beans>\s*$|$r|' conf/global.xml
fi

# Agent beans generated from hub/agents/agents.csv (deploy/gen-agents-xml.py) live in a
# bind-mounted directory. Defining shibboleth.sp.AgentResolverResources replaces the plugin's
# default resource list (postconfig.xml), so list the static agents.xml too. "conditional:"
# tolerates a missing file. Changes are picked up on reload, without a rebuild.
if ! grep -q 'shibboleth.sp.AgentResolverResources' conf/global.xml; then
  cat > /tmp/agent-resources.xml <<'XML'
    <!-- SP hub: agent definitions = static conf/sp/agents.xml + generated file. See hub/entrypoint.sh. -->
    <util:list id="shibboleth.sp.AgentResolverResources">
        <value>%{idp.home}/conf/sp/agents.xml</value>
        <value>conditional:%{idp.home}/conf/sp/generated/agents-generated.xml</value>
    </util:list>

</beans>
XML
  perl -0pi -e 'BEGIN{local $/; open F,"</tmp/agent-resources.xml"; $r=<F>; close F} s|</beans>\s*$|$r|' conf/global.xml
fi

# Export the hub's TLS cert (made by the IdP installer for hub.localtest) for agents.
if [ -d /tls-export ]; then
  openssl pkcs12 -in credentials/idp-userfacing.p12 -passin pass:changeit -nokeys -clcerts 2>/dev/null \
    | openssl x509 > /tls-export/hub.crt
  chmod 644 /tls-export/hub.crt
fi

# OIDC plugin wiring per OIDCBasics (agents.xml is COPY'd with the import already in it).
grep -q 'oidc-claim-rules.xml' conf/attributes/default-rules.xml || \
  sed -i 's|</beans>|    <import resource="oidc-claim-rules.xml" />\n</beans>|' conf/attributes/default-rules.xml
# (client-secret credential bean lives in the COPY'd conf/sp/oidc-credentials.xml)

# PoC logging: DEBUG for the hub and OIDC packages (shows claims received, agent ops).
grep -q 'name="net.shibboleth.sp"' conf/logback.xml || \
  sed -i 's|</configuration>|    <logger name="net.shibboleth.sp" level="DEBUG" />\n    <logger name="net.shibboleth.oidc" level="DEBUG" />\n</configuration>|' conf/logback.xml

# Foreground Jetty via the plugin's script (sets -Didp.home, tmpdir, log dir).
# JETTY_HOME / JETTY_BASE come from the image ENV; http host was opened in the Dockerfile.
exec bin/runjetty.sh run
