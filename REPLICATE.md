# Replicating shibSP4clean

This guide walks you through building your own copy of this environment: a Shibboleth SP v4 **hub** and **agent** in Docker, with users logging in through Google via OpenID Connect. At the end, a browser login at `https://localhost/secure/` puts your Google attributes into an agent session.

It describes <https://github.com/khazelton/shibSP4clean> as of the commit that last changed this file (`git log -1 -- REPLICATE.md`), last verified on 2026-11-04 with hub nightly 0.0.3-35.

## What you are building

```
browser ──https──▶ agent  (Rocky 9 + Apache httpd + mod_shib4, 172.31.0.20, ports 80/443)
                     │  basic auth over TLS, as service account sa3-sp4-agent
                     ▼
                   hub    (IdP 5.2.3 + Jetty 12.1 + SP hub plugins, 172.31.0.10, alias hub.localtest)
                     │  OIDC relying party
                     ▼
                   Google
```

- The **agent** protects `/secure`. When there's no session it asks the hub to start a login, sends the browser to Google, and hands the returned code to the hub.
- The **hub** does the OIDC work: code exchange, ID token validation, UserInfo, attribute mapping and filtering. It returns the attributes to the agent.
- The agent proves who it is to the hub with a username and secret. The hub checks the secret against an htpasswd file and the source address against an allowed range.

There's no application behind the agent. `/secure` still forwards to a backend called `app`, which doesn't exist here, so after login that page shows a proxy error. That's expected. You inspect the result at `https://localhost/Shibboleth.sso/Session` instead.

## Before you start

You need:

- **Docker** with Compose v2 (Docker Desktop on macOS or Windows, or Docker Engine on Linux). The images were built on Apple silicon (arm64). The Shibboleth RPM and the base images also exist for x86_64.
- **git**, **openssl** and **python3** on the host. The helper scripts use them.
- **Free ports** 80, 443 and 127.0.0.1:8080, and no existing Docker network on `172.31.0.0/24`.
- A **Google account** and access to the Google Cloud Console, to create an OAuth client.
- About 2 GB of disk for the images. The first build downloads the IdP, Jetty and the plugins and takes several minutes.

## Step 1: Create a Google OAuth client

The hub is an OIDC relying party, so Google needs to know about it.

1. In the Google Cloud Console, open **APIs & Services → OAuth consent screen**. Choose **External**, leave it in **Testing**, and add your own Google account as a test user.
2. Open **Credentials → Create credentials → OAuth client ID**, application type **Web application**.
3. Under **Authorized redirect URIs**, add exactly:
   ```
   https://localhost/Shibboleth.sso/Validate
   ```
   That's the agent's token consumer. Google sends the browser back to the agent, never to the hub.
4. Save, and keep the **client ID** and **client secret** for Step 3.

## Step 2: Get the files

### Option A: clone (recommended)

```sh
git clone https://github.com/khazelton/shibSP4clean.git
cd shibSP4clean
git checkout "$(git log -1 --format=%h -- REPLICATE.md)"   # optional: the exact tree this guide describes
```

Go to Step 3.

### Option B: build the tree yourself

Use this if you want to understand each piece, or to start your own repository with its own history. Create an empty directory, run `git init`, and create the files below. Copy their contents from the repository (`https://github.com/khazelton/shibSP4clean/blob/main/<path>`; to match this guide exactly, replace `main` with the commit that last changed `REPLICATE.md`). Keep the paths exactly as listed: `compose.yaml` and the scripts expect them.

**Top level**

| File | What it does |
|---|---|
| `compose.yaml` | Two services, `hub` and `agent`, on network `sp4` (`172.31.0.0/24`). Pins the hub at `.10` with alias `hub.localtest` and the agent at `.20`. Bind-mounts the agent config, the htpasswd directory and the generated agent list; shares the hub's TLS certificate with the agent through the `hub-tls` volume. |
| `.gitignore` | Keeps secrets out of git: `.env`, `agent/conf/shibboleth-sp/agent.pwd`, `hub/htpasswd/*.htpasswd`, plus `*.ldif` and `compare.html`. |
| `gen-agent-secret.sh` | Creates or rotates an agent's secret and delivers it to both ends: an `$apr1$` hash in `hub/htpasswd/agents.htpasswd`, and the plain secret in `agent/conf/shibboleth-sp/agent.pwd`. |
| `gen-agents-xml.py` | Turns `hub/agents/agents.csv` into hub agent beans in `hub/agents/generated/agents-generated.xml`, after validating it. |
| `gen_compare.py` | Optional. Builds the reviewer page that compares this repo with the PoC it came from. It isn't needed to run the stack. |
| `README.md` | Short description of the stack. |

**Agent** (`agent/`)

| File | What it does |
|---|---|
| `Dockerfile` | Rocky Linux 9 with `httpd` and `mod_ssl`. Adds the Shibboleth yum repository and installs `shibboleth-sp-4.0.0beta1`. Makes a self-signed certificate for `localhost`, switches Apache to the event MPM, and sets aside the shipped `shib4.conf`. |
| `conf/httpd/shib4-poc.conf` | Loads `mod_shib4`. Redirects port 80 to 443. Protects `/secure` with `requireSession 1` and passes attributes on as `X-Shib-*` headers. Proxies `/secure` and `/public` to `app:8081`. |
| `conf/shibboleth-sp/agent.ini` | Agent settings. `[remoting]` points at `https://hub.localtest:8443/idp/profile/sp/` with `authMethod = basic`, `agentID = sa3-sp4-agent`, the hub certificate as `tlsCAFile`, and the secret read from `agent.pwd`. |
| `conf/shibboleth-sp/handlers.ini` | The `/Shibboleth.sso` handlers: Status, Session (shows attribute values), Login, Validate, Logout. |
| `conf/shibboleth-sp/request-map.xml` | Empty map; Apache directives carry the access rules. |

**Hub** (`hub/`)

| File | What it does |
|---|---|
| `Dockerfile` | Built in layers: <br>1. IdP 5.2.3 release, installed unattended. It serves only as the plugin host. <br>2. Jetty 12.1.4 via the Jetty plugin, with listeners opened beyond loopback. <br>3. The newest *signed* nightly of the SP hub plugins `sp-dist`, `oidc-common-dist` and `sp-oidc-dist`, checked against the Shibboleth snapshot PGP keys. <br>Then a TLS certificate for `hub.localtest` and the OIDC signing keys, and finally the files from `conf/` and `entrypoint.sh` are copied in. |
| `entrypoint.sh` | Runs at every start. Writes the Google client ID and secret into `sp.properties` / `oidc.properties`, requests the `profile,email` scopes, and turns on basic auth for agents. Adds to `global.xml` a validator chain (internal secret, then LDAP if configured, then htpasswd) and the list of agent definition files. Exports the hub certificate for the agent, wires in the OIDC claim rules, and sets DEBUG logging for the hub. Then starts Jetty. |
| `conf/agents.xml` | The static half of the agent configuration: relying-party overrides and the OIDC credential import. The agents themselves come from the generated file. |
| `conf/oidc-credentials.xml` | Enables only the `client_secret` credential toward Google. |
| `conf/attribute-filter.xml` | Releases the Google claims. The stock policy silently drops `mail`. |
| `conf/attribute-resolver.xml` | Empty. The stock `uid` definition errors on a hub-only IdP. |
| `agents/agents.csv` | One row per agent: `agent_id,group,allowed_ranges,usernames,owner`. The single agent is `sp4-agent.localtest`, allowed from `172.31.0.20/32`, with usernames `sa1-sp4-agent sa2-sp4-agent sa3-sp4-agent`. Only `sa3` is used here. |
| `agents/templates/basic.xml` | Bean template for agents in group `basic`. |
| `agents/generated/agents-generated.xml` | Output of `gen-agents-xml.py`. Commit it, so a fresh copy starts without running the generator. |
| `agents/README.md`, `htpasswd/README.md` | Notes on the agent list and the htpasswd file (supported hashes: `$apr1$`, `{SHA}`, crypt; **not** bcrypt). |

Make the scripts executable (`chmod +x gen-agent-secret.sh gen-agents-xml.py gen_compare.py hub/entrypoint.sh`), and regenerate the agent list so you know the generator works:

```sh
./gen-agents-xml.py
```

## Step 3: Create the secrets

None of these go into git.

1. **Google client.** Create `.env` in the repository root:
   ```sh
   cat > .env <<'EOF'
   GOOGLE_CLIENT_ID=<your client id>.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=<your client secret>
   EOF
   chmod 600 .env
   ```
2. **Agent credential.** Generate the secret for `sa3-sp4-agent`:
   ```sh
   ./gen-agent-secret.sh --htpasswd sa3-sp4-agent
   ```
   This writes the hash to `hub/htpasswd/agents.htpasswd` and the secret to `agent/conf/shibboleth-sp/agent.pwd`.

Check that git ignores all three:

```sh
git status --short --ignored | grep -E '\.env|agent\.pwd|htpasswd$'
```

Each line should start with `!!`.

## Step 4: Build the images

```sh
docker compose build
```

What happens:

- **Agent** (a minute or two): the Shibboleth yum repository is added and the SP v4 beta RPM is installed.
- **Hub** (several minutes): the IdP is downloaded and installed, then Jetty, then the three SP hub plugins. The build prints the plugin URLs it chose:
  ```
  core: …/sp-dist-0.0.3-20261104.140648-35.tar.gz
  oidc-common: …/oidc-common-dist-3.4.0-20261103.012517-322.tar.gz
  oidc: …/sp-oidc-dist-0.0.3-20261104.140853-35.tar.gz
  ```
  Lines like `Algorithm failed runtime support check … ripemd160` are harmless: the JDK has no RIPEMD-160.

> **Nightly drift.** The hub plugins are pre-release nightly snapshots. The snapshot repository keeps only the newest build of each version, so they can't be pinned. Your build will pick up whatever is newest that day. The configuration here is known to work on nightlies -32 and -35. If a later nightly breaks it, the hub log names the failing bean; compare with the defects listed in the Shibboleth dev-list threads.

Confirm what you got:

```sh
docker run --rm --entrypoint bin/plugin.sh sp4clean-hub -l
docker run --rm sp4clean-agent rpm -q shibboleth-sp
```

## Step 5: Start the stack and check the agent↔hub link

```sh
docker compose up -d
```

Compose starts the hub first and waits for its healthcheck (`/idp/status`) before starting the agent. That takes about 20 seconds.

Check that the agent can reach and authenticate to the hub:

```sh
curl -sk https://localhost/Shibboleth.sso/Status | grep -o '<RemotingService><OK/>'
```

You should see `<RemotingService><OK/>`. To see how the hub authenticated the agent:

```sh
docker exec sp4clean-hub grep -h 'Credential Validator' /opt/shibboleth-idp/logs/idp-process.log | tail -3
```

Expect the internal validator to step aside, then `spagent-htpasswd: Login by 'sa3-sp4-agent' succeeded`.

## Step 6: Log in

1. Open `https://localhost/secure/` and accept the self-signed certificate warning.
2. You're sent to Google. Sign in with the test user from Step 1.
3. Google returns you to `https://localhost/Shibboleth.sso/Validate`, and the agent hands the code to the hub. You land on `/secure/` and see a **proxy error**. That's expected, because there's no app.
4. Open `https://localhost/Shibboleth.sso/Session`. You should see a session with `sub`, `mail`, `displayName`, `givenName` and `sn` and their values.

That's the end state: a working SP v4 hub and agent doing OIDC against Google.

## Day-to-day operations

- **Rotate the agent secret:** rerun `./gen-agent-secret.sh --htpasswd sa3-sp4-agent`, then `docker compose up -d --no-deps --force-recreate agent`. The hub re-reads the htpasswd file on its own.
- **Add or change an agent:** edit `hub/agents/agents.csv` and run `./gen-agents-xml.py --reload`. It validates the list, rewrites the generated file and reloads the hub's agent resolver, with no rebuild or restart. Without `--reload` the hub picks the change up within 5 minutes.
- **Pick up a newer hub nightly:** `docker compose build --no-cache hub && docker compose up -d`.
- **Logs:** `docker compose logs -f hub` covers startup; per-request hub logs are in the container at `/opt/shibboleth-idp/logs/idp-process.log`.
- **Stop:** `docker compose down`. Named volumes (hub logs, hub certificate, agent sessions) survive. `docker compose down -v` removes them too.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `GOOGLE_CLIENT_ID not set` at start | `.env` missing or misnamed | Create `.env` in the repository root (Step 3). |
| `Bind for 0.0.0.0:443 failed` | Something else holds port 80 or 443 | Stop it, or change the agent's published ports. Google only accepts the redirect URI you registered, so update that too. |
| `Pool overlaps with other one on this host` | Another Docker network uses `172.31.0.0/24` | Pick another subnet in `compose.yaml`, then change the agent's address there and in `hub/agents/agents.csv`, and rerun `./gen-agents-xml.py`. |
| Status page lacks `<RemotingService><OK/>` | Agent can't authenticate | Check that `agent.pwd` and `agents.htpasswd` came from the same run of `gen-agent-secret.sh`, and that `agentID` in `agent.ini` is `sa3-sp4-agent`. Hub responses are always HTTP 200; look for `event InvalidCredentials` or `AccessDenied` in the hub log. |
| Hub never becomes healthy | Config error at startup | `docker compose logs hub`, and look for `AgentResolverService` or `BeanCreationException`. Usually a newer nightly. |
| Google says `redirect_uri_mismatch` | Redirect URI not registered exactly | Register `https://localhost/Shibboleth.sso/Validate` on the OAuth client (Step 1). |
| Session shows no `mail` | Stock attribute filter in use | Make sure `hub/conf/attribute-filter.xml` is the repository's version, and rebuild the hub. |

## Known limits

- **Pre-release software.** The agent is `4.0.0beta1` and the hub plugins are nightlies. Expect change.
- **Development certificates.** The agent's `localhost` certificate and the hub's `hub.localtest` certificate are self-signed and made at build time. The keystore passwords are the placeholder `changeit`.
- **Single host only.** The hub accepts the agent only from `172.31.0.20`, and the agent finds the hub through the Docker network alias `hub.localtest`.
- **Same ports as the PoC.** This stack and the PoC it came from use the same host ports and the same Google redirect URI, so run one at a time.
