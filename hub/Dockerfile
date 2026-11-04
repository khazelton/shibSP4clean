# SP v4 Hub: IdP 5.2.3 (as plugin host only) + Jetty 12.1 + shibd core/OIDC snapshot plugins
FROM eclipse-temurin:17-jdk

ARG IDP_VERSION=5.2.3
ARG JETTY_VERSION=12.1.4
# Hub plugins are nightly snapshots; only the newest tarball per version dir is kept,
# so the exact filename is resolved at build time (see the plugin RUN step).
ARG SP_SNAPSHOT=0.0.3-SNAPSHOT
ARG OIDC_COMMON_SNAPSHOT=3.4.0-SNAPSHOT
ARG SNAP_BASE=https://build.shibboleth.net/maven/snapshots/net/shibboleth

ENV IDP_HOME=/opt/shibboleth-idp
# Real paths the Jetty plugin creates (no jetty-home/jetty-base symlinks in this layout)
ENV JETTY_HOME=${IDP_HOME}/jetty-dist/jetty-home-${JETTY_VERSION}
ENV JETTY_BASE=${IDP_HOME}/jetty-base-12

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gpg openssl && rm -rf /var/lib/apt/lists/*

# --- IdP (unattended). Values are placeholders: this IdP never acts as an IdP.
WORKDIR /tmp/idp-src
RUN curl -fsSL "https://shibboleth.net/downloads/identity-provider/${IDP_VERSION}/shibboleth-identity-provider-${IDP_VERSION}.tar.gz" \
      | tar xz --strip-components=1 \
 && printf '%s\n' \
      "idp.target.dir=${IDP_HOME}" \
      "idp.host.name=hub.localtest" \
      "idp.entityID=https://hub.localtest/idp/shibboleth" \
      "idp.scope=localtest" \
      "idp.keystore.password=changeit" \
      "idp.sealer.password=changeit" \
      "idp.noprompt=true" \
      > /tmp/idp.install.properties \
 && bin/install.sh --propertyFile /tmp/idp.install.properties --noPrompt \
 && rm -rf /tmp/idp-src /tmp/idp.install.properties

WORKDIR ${IDP_HOME}

# --- Jetty via the Jetty Base plugin
# plugin.sh prompts to trust the signing key unless a truststore is supplied ("No Console Attached").
RUN curl -fsSL https://shibboleth.net/downloads/PGP_KEYS -o /tmp/PGP_KEYS \
 && bin/plugin.sh --truststore /tmp/PGP_KEYS -I net.shibboleth.idp.plugin.jetty \
 && bin/downloadjetty.sh ${JETTY_VERSION} \
 && rm -f /tmp/PGP_KEYS jetty-dist/jetty-home-${JETTY_VERSION}.tar.gz \
 # plugin pins listeners to 127.0.0.1; the agent lives in another container
 && sed -i 's/^jetty.http.host=127.0.0.1/jetty.http.host=0.0.0.0/; s/^jetty.ssl.host=127.0.0.1/jetty.ssl.host=0.0.0.0/' jetty-base-12/start.d/shibboleth.ini \
 && test -e "${JETTY_HOME}/start.jar"

# --- SP hub plugins (snapshots, signed with the snapshot keyring)
# latest_tgz DIR_URL -> URL of the newest *.tar.gz that also has a .asc signature
# (the very newest nightly can sit unsigned for a while; plugin.sh needs the .asc)
RUN curl -fsSL https://shibboleth.net/downloads/SHIBBOLETH_SNAPSHOT_PGP_KEYS -o /tmp/SNAPSHOT_KEYS \
 && latest_tgz() { curl -fsSL "$1/" | grep -oE '[a-z-]+-dist-[0-9.]+-[0-9]{8}\.[0-9]{6}-[0-9]+\.tar\.gz\.asc' | sort -u | tail -1 | sed "s|\.asc$||; s|^|$1/|"; } \
 && SP_DIST_URL=$(latest_tgz "${SNAP_BASE}/sp/sp-dist/${SP_SNAPSHOT}") \
 && OIDC_COMMON_URL=$(latest_tgz "${SNAP_BASE}/oidc/oidc-common-dist/${OIDC_COMMON_SNAPSHOT}") \
 && SP_OIDC_DIST_URL=$(latest_tgz "${SNAP_BASE}/sp/sp-oidc-dist/${SP_SNAPSHOT}") \
 && echo "core: $SP_DIST_URL" && echo "oidc-common: $OIDC_COMMON_URL" && echo "oidc: $SP_OIDC_DIST_URL" \
 && bin/plugin.sh --noCheck --truststore /tmp/SNAPSHOT_KEYS -i "${SP_DIST_URL}" \
 && bin/plugin.sh --noCheck --truststore /tmp/SNAPSHOT_KEYS -i "${OIDC_COMMON_URL}" \
 && bin/plugin.sh --noCheck --truststore /tmp/SNAPSHOT_KEYS -i "${SP_OIDC_DIST_URL}" \
 && rm -f /tmp/SNAPSHOT_KEYS \
 && bin/plugin.sh -l

# --- Jetty TLS cert for the agent-facing listener. The installer ignored idp.host.name and
# issued its cert for the build container's IP, so replace credentials/idp-userfacing.p12
# (the keystore start.d/shibboleth.ini points at, password "changeit") with hub.localtest.
RUN openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
      -subj "/CN=hub.localtest" -addext "subjectAltName=DNS:hub.localtest" \
      -keyout /tmp/hub.key -out /tmp/hub.crt \
 && openssl pkcs12 -export -name hub.localtest -inkey /tmp/hub.key -in /tmp/hub.crt \
      -out credentials/idp-userfacing.p12 -passout pass:changeit \
 && rm -f /tmp/hub.key /tmp/hub.crt

# --- OIDC RP keys (OIDCBasics: must exist before credentials import or AgentResolverService fails)
RUN mkdir -p credentials/sp \
 && bin/jwtgen-sp.sh -t RSA -s 2048 -u sig -i defaultRSASign | tail -n +2 > credentials/sp/sp-signing-rs.jwk \
 && bin/jwtgen-sp.sh -t EC -c P-256 -u sig -i defaultECSign | tail -n +2 > credentials/sp/sp-signing-es.jwk \
 && bin/jwtgen-sp.sh -t RSA -s 2048 -u enc -i defaultRSAEnc | tail -n +2 > credentials/sp/sp-encryption-rsa.jwk

# PoC overrides (see comments in each file):
#  - oidc-credentials.xml: enables only the client_secret credential
#  - attribute-filter.xml: releases Google claims; stock policy silently dropped "mail"
#  - attribute-resolver.xml: empty; stock "uid" definition errors on a hub-only IdP
#  - agents.xml: the networked agent with basic auth + address check (Phase 2)
COPY conf/oidc-credentials.xml conf/sp/oidc-credentials.xml
COPY conf/agents.xml conf/sp/agents.xml
COPY conf/attribute-filter.xml conf/attribute-filter.xml
COPY conf/attribute-resolver.xml conf/attribute-resolver.xml

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
