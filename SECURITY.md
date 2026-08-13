# Security policy

**English** | [Français](SECURITY.fr.md)

## Supported versions

Security fixes are applied to the latest published release and the `main`
branch. Older releases are not maintained; users should upgrade before
reporting a problem that may already have been corrected.

## Reporting a vulnerability

Please do not open a public issue or pull request for a suspected security
vulnerability. Use GitHub's
[private vulnerability reporting form](https://github.com/CyrilP/hass-deltadore-tydom-component/security/advisories/new)
so the maintainers can investigate before details are disclosed publicly.

Include, where possible:

- the affected integration and Home Assistant versions;
- a description of the impact and the conditions required to reproduce it;
- minimal reproduction steps or a proof of concept;
- relevant logs with credentials and personal information removed; and
- any suggested mitigation.

Never include TYDOM passwords, account passwords, access tokens, alarm PINs,
complete MAC addresses or unredacted household/device data. Please allow the
maintainers time to confirm the report and prepare a fix before publishing any
details.

## Security hardening already applied

An audit in May 2026 identified several weaknesses. Its fixes were reapplied
in June 2026 after intervening merges had overwritten parts of them. The
current code includes the following protections:

- request bodies are serialised with `json.dumps()` rather than assembled by
  string concatenation;
- alarm PINs, cloud credentials and request bodies containing secrets are not
  written verbatim to logs;
- TLS certificate verification is required for cloud connections to
  `mediation.tydom.com`, while local gateways retain the explicitly documented
  exception required for their self-signed certificates;
- values interpolated into WebSocket paths are URL-encoded;
- configuration-flow exception traces are handled by Home Assistant logging
  rather than printed directly to standard output;
- invalid host, MAC, email and alarm-zone input is logged without echoing the
  submitted value;
- MAC addresses and email addresses receive stricter format validation; and
- debug trace files use a managed context and a configurable Home Assistant
  configuration path.

These protections originated in commit `db71301`, were first reapplied in
commit `a47f338`, and were reapplied again after the v0.21 rebase. This section
replaces the former dated audit notes and is intended to remain the maintained
record.

## Known residual risk

Local TYDOM Digest authentication still relies on an internal implementation
detail of `requests` (`HTTPDigestAuth._thread_local`). Replacing it requires a
larger authentication rewrite because the asynchronous client used by the
integration does not provide equivalent Digest authentication directly.

Strict TLS verification may also reject an intercepting proxy whose
certificate is not trusted by the Home Assistant host. That is expected secure
behaviour rather than a reason to disable verification.
