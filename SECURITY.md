# Security Policy

## Supported Versions

Pylar is currently on the `0.1.x` initial public release line.

| Component | Supported versions | Status |
| --- | --- | --- |
| `pylar-framework` | `0.1.x` | Supported |
| `pylar-admin` | `0.1.x` | Supported |
| pre-`0.1.0` builds | unsupported | Best effort only |

The canonical compatibility/support policy lives at
[`docs/site/support-policy.md`](docs/site/support-policy.md).

## Reporting a Vulnerability

Preferred channel: **GitHub Security Advisories** on the affected
repository (`pylar-foundation/pylar-framework` or
`pylar-foundation/pylar-admin`) — use the "Report a vulnerability"
button under the *Security* tab.

Email fallback: `pylar-foundation@vsibiri.info`.

Please include:

- affected package and version
- impact and attack prerequisites
- reproduction steps or proof of concept
- suggested fix, if available

Do not open a public issue for unpatched vulnerabilities.

## Response Expectations

- Initial acknowledgement target: 3 business days
- Triage target: 7 business days
- Fix timing: based on severity and exploitability

When a report is confirmed, maintainers will:

1. reproduce and triage the issue
2. prepare a fix and regression coverage
3. publish a release note and upgrade guidance
4. backport only where the support matrix says a line is still supported

## Disclosure

Pylar follows coordinated disclosure. Public advisories should be published only after a fix or clear mitigation is available.
