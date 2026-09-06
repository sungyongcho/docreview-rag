# Attribution & Licensing

## Synthetic documents (`seed/synthetic/`)

All files in `seed/synthetic/` and all files in `golden/` were authored from scratch for
this project. "Northwind Labs" and every policy, figure, and name in these documents are
fictional. There is **no real company, personal, or confidential data** in this dataset.

These synthetic files are released by the project author into the public domain
(CC0 1.0 — no rights reserved). You may use, modify, and redistribute them freely, with no
attribution required.

## Public documents (`seed/public/`)

This folder is intentionally empty in the base dataset. If you add real public documents to
demonstrate that the system works on real-world text, store them **verbatim** here and
record each one below with its license. Pin an exact version so your golden answers do not
silently break when the upstream document changes.

### Template — RFC 9110 (HTTP Semantics)

> Source: IETF RFC 9110, "HTTP Semantics" (immutable; cite by RFC number).
> URL: https://www.rfc-editor.org/rfc/rfc9110.txt
> Copyright (c) 2022 IETF Trust and the persons identified as the document authors.
> Used under BCP 78 / the IETF Trust Legal Provisions: verbatim portions may be reproduced
> with the copyright notice retained; the text is not modified. Code components, if any, are
> under the Simplified BSD License.

### Template — OWASP ASVS

> Source: OWASP Application Security Verification Standard, version <PIN VERSION, e.g. v5.0.0>.
> Repo / commit: https://github.com/OWASP/ASVS  (record the exact tag or commit hash)
> License: Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0).
> Stored verbatim. Attribution: "OWASP ASVS, CC BY-SA 4.0." If any excerpt is adapted,
> that adaptation must also be CC BY-SA 4.0; the application code is licensed separately and
> is not an adaptation of this document.

### Template — NIST CSF / SP 800-series

> Source: NIST <publication id and version>.
> URL: <nist.gov link>
> Status: U.S. public domain (NIST works are not subject to U.S. copyright). Credit line:
> "Reprinted courtesy of the National Institute of Standards and Technology, U.S. Department
> of Commerce." Note: confirm no embedded third-party copyrighted material in the excerpt.

When you add a public document, also add its section references to the golden files and
re-run `python data/validate_dataset.py`.
