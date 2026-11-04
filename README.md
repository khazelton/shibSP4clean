# shibSP4clean

Shibboleth SP v4 prerelease, hub + agent, rebuilt from the install steps and config of
`../shibSp4PoC/deploy`, without LDAP or the demo app.

- `agent/`: Rocky 9 + httpd, `shibboleth-sp-4.0.0beta1` RPM from the Shibboleth yum repo;
  self-signed cert for `localhost`, event MPM, vhost in `conf/httpd/shib4-poc.conf`,
  agent config in `conf/shibboleth-sp/` (bind-mounted).
- `hub/`: IdP 5.2.3 tarball → Jetty 12.1 via `plugin.sh` → nightly snapshot plugins
  `sp-dist`, `oidc-common-dist`, `sp-oidc-dist` (newest signed tarball, picked at build time);
  TLS cert for `hub.localtest`, OIDC RP JWKs, conf overrides in `conf/`, `entrypoint.sh`.
- Agents are generated from `hub/agents/agents.csv` by `./gen-agents-xml.py`.

Differences from the PoC:

- Subnet `172.31.0.0/24` (agent `.20`, hub `.10`), so it doesn't clash with the PoC network.
- No LDAP: the agent authenticates as `sa3-sp4-agent` from `hub/htpasswd/agents.htpasswd`.
- No app: `/secure` and `/public` still proxy to `app:8081`, so after login they return a
  proxy error. Check the session at `https://localhost/Shibboleth.sso/Session`.
- Same host ports 80/443 as the PoC, and the same Google redirect URI: run one stack at a time.

## Secrets (gitignored)

- `.env`: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (copied from the PoC).
- `hub/htpasswd/agents.htpasswd` and `agent/conf/shibboleth-sp/agent.pwd`:
  `./gen-agent-secret.sh --htpasswd sa3-sp4-agent` (rerun to rotate).

## Run

```sh
docker compose build                 # --no-cache to pick up a newer hub nightly
docker compose up -d
curl -sk https://localhost/Shibboleth.sso/Status | grep -o '<RemotingService><OK/>'
open https://localhost/secure/       # Google login; then /Shibboleth.sso/Session
```
