# The security lens

Used when a brief names `lens: Security`. A security finding shows the path from untrusted input to the sink (the
`path:line` of the entry, each step, the sink); without that path it is unsure, not a finding.

## Checklist

- **Injection:** untrusted input reaching a SQL query, a shell command, a file path (`..`, absolute paths, links) or a template.
- **Auth and authorization:** a route or action with no check, a check done after the effect, one user reaching another's data.
- **Secrets:** a hardcoded key or password; a secret or token written to a log or an error message.
- **Crypto:** a weak or home-made algorithm, a fixed IV or salt, a predictable random source used for a token or key.
- **Trust boundaries:** input from a user, file, network or environment used without parsing its type, size and range.
- **Races:** a check and the use it guards split in time (time-of-check to time-of-use), a file or balance changed in between.
- **Permissive config:** CORS open to all, debug mode on, a public bucket, a wide permission.
- **Supply chain:** a package name one letter off a known one, an unpinned install, a script piped into a shell.
- **Code execution:** `eval`, `exec`, `pickle` or other unsafe deserialization of untrusted data.
- **XSS:** untrusted text written into a page as markup or script without escaping.

## Do not report

- Denial of service, rate limiting, memory or CPU exhaustion.
- Generic input validation with no proven impact.
- Open redirects.
- An issue the project's "Review rules" section of `AGENTS.md` lists as accepted.
