You are preparing the threat intelligence section of an executive daily brief. The data below was collected from up to six public/free-tier feeds over the past {{ window_hours }} hours (as of {{ today }}).

**Payload:**
```json
{{ payload }}
```

**Metadata:**
```json
{{ metadata }}
```

**Instructions:**
- Open with a single-line headline summarising total threat volume across all sources (e.g. "3 new KEV entries, 28 high-severity CVEs, 47 malicious URLs tracked in the last 24 hours").
- **CISA KEV** — list each new entry as its own bullet: CVE ID, vendor/product, one-line description, and whether ransomware campaigns are known to use it.
- **NVD CVEs** — pick 3–5 entries with the highest CVSS score that are *not* already in the KEV list; include CVE ID, CVSS score, severity, and a concise description.
- **Infrastructure (URLhaus / ThreatFox / Feodo)** — one combined bullet per source describing the volume of new indicators and any notable clusters (e.g. dominant malware family, spike in a particular threat type).
- **AlienVault OTX** — one bullet per pulse: pulse name, adversary (if known), targeted countries/industries.
- Sources with `status: "skipped"` or `status: "error"` — mention briefly in a single parenthetical note, do not give them a full section.
- IoC values (IPs, URLs, domains) are already defanged in the payload; reproduce them exactly as shown.
- Do **not** editorialize or add remediation advice beyond what the source data provides.
- Write in a neutral, factual tone suitable for an executive briefing.

**Under `Attention`**, flag only:
- Any KEV entry where `ransomware` is `true`
- Any CVE with CVSS score ≥ 9.5
- Any single malware family with 10 or more IoCs across ThreatFox or Feodo entries
- Any OTX pulse targeting the Finance industry

If none of these conditions apply, omit the `Attention` line entirely.

**Output format (use exactly this markdown structure):**

### Threat Intel
_<one-line headline with aggregate counts>_

- <CISA KEV entry: CVE, vendor/product, description, ransomware flag>
- <NVD CVE: CVE ID, CVSS score, severity, description>
- URLhaus: <volume + notable clusters>
- ThreatFox: <volume + notable clusters> *(or omit if skipped/error)*
- Feodo: <volume + notable clusters> *(or omit if skipped/error)*
- OTX: <pulse name — adversary, countries, industries> *(or omit if skipped/error)*

**Attention:** <only if a trigger condition above is met>
