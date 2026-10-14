# Security policy

Please report vulnerabilities **privately**. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) on this
repository, not a public issue.

Include the OS, the release version or commit, and a PDF or steps that
reproduce the problem. Never attach a real shipping label: labels contain
other people's names and home addresses. A synthetic PDF is enough.

In scope: anything that lets a crafted PDF, or a file dropped into the
watched folder, do something other than produce a sanitized 4x6 PDF. That
includes code execution, writes outside the output path, active content
surviving into the output, and resource exhaustion past the documented
limits (see "Security" in the README).

Supported versions: the latest release only.
