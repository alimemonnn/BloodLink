# Security policy

If you find a vulnerability (for example access to another person's request or conversation, or a way to change
unit counts without a hospital), please email the maintainer privately instead of opening a public issue, and give
steps to reproduce. Please do not test against real people's data. We aim to reply within a few days.

Built-in protections: CSRF tokens on every state-changing request, strict Content-Security-Policy, hashed
passwords, per-object authorisation (other people's records return 404), row locking on donation counting,
rate limiting on logins and chat, and an audit log.
