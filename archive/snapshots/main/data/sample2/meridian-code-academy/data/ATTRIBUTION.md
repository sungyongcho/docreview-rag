# Attribution & Licensing

## Originality statement

Meridian Code Academy ("MCA") is a fictional school. Every document in `seed/synthetic/`
and every file in `golden/` is an original work written for this project. The set follows
the *general genre* of school and platform policies (a privacy/retention policy, API terms,
campus rules with tiered sanctions, exam rules, an enrollment/progression document, and an
IT/security charter), but the wording, the specific figures (token TTL, secret-rotation
period, retention durations, fees, sanction tiers, deadlines), the structure, and the
scenarios are invented for this dataset.

These files are **not derived from, and contain no text from, any real institution's
documents.** No real persons, policies, or data are described.

## License

Released into the public domain (CC0 1.0 — no rights reserved). Use, modify, and
redistribute freely; no attribution required.

## Adding real public documents (`seed/public/`)

This folder is empty in the base dataset. If you later add a real public document to show
the system works on real-world text, store it **verbatim**, pin an exact version, and record
its source and license here. Do not add documents you are contractually bound not to
republish (for example, terms of use you signed that restrict redistribution); model them
with an original synthetic document instead, as this pack does.

After adding any document, add its section references to the golden files and run
`python data/validate_dataset.py`.
