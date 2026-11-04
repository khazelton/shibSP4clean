# SP v4 Agent: Rocky 9 + Apache 2.4 + shibboleth-sp 4.0.0beta1
FROM rockylinux:9

# curl-minimal is preinstalled and conflicts with curl; it is enough for our needs.
RUN dnf -y install httpd mod_ssl openssl && dnf clean all

# Shibboleth yum repo (same repo as SP3; SP4 ships as package "shibboleth-sp")
RUN curl -fsSL "https://shibboleth.net/cgi-bin/sp_repo.cgi?platform=rockylinux9" \
      -o /etc/yum.repos.d/shibboleth.repo \
 && dnf -y install shibboleth-sp-4.0.0beta1 \
 && dnf clean all

# Self-signed cert for https://localhost (Google accepts localhost redirect URIs)
RUN openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
      -subj "/CN=localhost" \
      -addext "subjectAltName=DNS:localhost" \
      -keyout /etc/pki/tls/private/localhost.key \
      -out    /etc/pki/tls/certs/localhost.crt \
 && chmod 600 /etc/pki/tls/private/localhost.key

# Apache: event MPM (docs say not prefork), ServerName, drop the shipped example
RUN sed -i 's/^LoadModule mpm_prefork_module/#LoadModule mpm_prefork_module/; s/^#LoadModule mpm_event_module/LoadModule mpm_event_module/' /etc/httpd/conf.modules.d/00-mpm.conf \
 && echo "ServerName localhost" > /etc/httpd/conf.d/00-servername.conf \
 && echo "UseCanonicalName On" >> /etc/httpd/conf.d/00-servername.conf \
 && rm -f /etc/httpd/conf.d/welcome.conf \
 && mv /etc/httpd/conf.d/shib4.conf /etc/httpd/conf.d/shib4.conf.shipped \
 # "00-" so the PoC vhost is the first *:443 vhost (ahead of ssl.conf's _default_)
 && echo "IncludeOptional conf.d/poc/*.conf" > /etc/httpd/conf.d/00-poc-include.conf

# /etc/shibboleth-sp is bind-mounted read-only from deploy/agent/conf/shibboleth-sp;
# keep the shipped copies for reference and give the session cache a writable home.
RUN cp -a /etc/shibboleth-sp /etc/shibboleth-sp.shipped \
 && mkdir -p /var/cache/shibboleth-sp && chown apache:apache /var/cache/shibboleth-sp

# Agent config is bind-mounted from deploy/agent/conf at runtime (see compose.yaml)

EXPOSE 80 443
CMD ["/usr/sbin/httpd", "-DFOREGROUND"]
