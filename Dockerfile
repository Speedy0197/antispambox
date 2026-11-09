FROM python:3.12-slim-trixie AS runtime

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Europe/Berlin
SHELL ["/bin/sh", "-ec"]
WORKDIR /root

# Signed Debian repositories provide both filter engines and the modern spamd service.
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d \
    && chmod 755 /usr/sbin/policy-rc.d \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates cron gnupg lighttpd logrotate redis-server rspamd rsyslog \
        spamassassin spamc spamd tini tzdata unattended-upgrades \
        geoip-database libgeo-ip-perl libgeography-countries-perl \
    && usermod -a -G mail redis \
    && rm /usr/sbin/policy-rc.d \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /root/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /root/requirements.txt

# Explicit sources: account volumes, local credentials and Git metadata are never copied.
COPY files/*.py /root/
COPY files/sa-channels files/spamassassin_user_prefs files/mailreport_logrotate /root/
COPY files/imap_accounts.example.json /root/imap_accounts.json
COPY files/rspamd_config/ /etc/rspamd/local.d/

RUN install -m 0644 /root/spamassassin_user_prefs /etc/spamassassin/user_prefs.cf \
    && install -m 0644 /root/mailreport_logrotate /etc/logrotate.d/antispambox \
    && printf '\nbayes_path /var/spamassassin/bayesdb/bayes\n' >> /etc/spamassassin/local.cf \
    && printf 'loadplugin Mail::SpamAssassin::Plugin::RelayCountry\n' > /etc/spamassassin/antispambox.pre \
    && sed -i 's|^dir .*|dir /var/spamassassin/bayesdb|' /etc/redis/redis.conf \
    && python3 /root/startup.py --configure \
    && python3 /root/learning_compat.py \
    && python3 /root/update_rules.py --install-schedule \
    && rspamadm configtest

FROM runtime AS tested
COPY tests/ /root/tests/
RUN python3 -m unittest discover -s /root/tests -v

VOLUME ["/var/spamassassin/bayesdb", "/root/accounts"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=3 \
    CMD ["python3", "/root/healthcheck.py"]
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "/root/startup.py"]
