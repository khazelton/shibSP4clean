# Hub agent credentials: flat-file option

Bind-mounted into the hub at `/opt/shibboleth-idp/credentials/sp/htpasswd/` (read-only). `agents.htpasswd` is gitignored and written by `../../gen-agent-secret.sh --htpasswd <username>`. The username must also be in the hub agent's `p:usernames` (`../conf/agents.xml`).

- Supported hashes: `$apr1$` (what the script writes), `{SHA}`, and crypt (`$5$`/`$6$`). bcrypt (`$2y$`, `htpasswd -B`) is **not** supported by the IdP's `HTPasswdCredentialValidator`.
- The hub re-reads the file when its modification time changes, so a rotation needs no restart.
- If the file is missing when the hub starts, the entrypoint logs a warning and leaves the htpasswd validator out. Create the file, then recreate the hub.
