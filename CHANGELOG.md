## Unreleased

- Modernize to Python 3.12 / Debian 13 with signed distro packages and pinned mailbox clients.
- Replace obsolete init wrappers with supervised foreground daemons and graceful shutdown.
- Support current spamd defaults and validated foreground reloads; add local health checks.
- Protect runtime account files from image builds and remove world-writable classifier storage.
- Verify offline learning, reload and restart persistence before publishing container images.
- Preserve passwords containing spaces or shell characters when invoking scanner clients.

- Use IPv4 loopback for the container Redis connection.
- Keep failed IRSD learning attempts retryable instead of caching them as learned.
- Consolidate daily rule updates with GPG support, per-channel status, validation and reload retries.
- Correct custom rule syntax and add regression checks.

Changelog
===

What has been done since last release.

Unreleased
---

* Integration of isbg and irsd


