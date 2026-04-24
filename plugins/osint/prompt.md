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
- **NVD CVEs** — if `nvd.status` is `"error"` or `"skipped"`, omit the NVD section entirely and mention it only in the parenthetical note with the other failed sources. If NVD data is present, pick 3–5 entries with the highest CVSS score that are *not* already in the KEV list; include CVE ID, CVSS score, severity, and a concise description. **Only use CVE IDs that appear verbatim in the payload — never invent or approximate CVE IDs.**
- **Infrastructure (URLhaus / ThreatFox / Feodo)** — one combined bullet per source describing the volume of indicators and any notable clusters (e.g. dominant malware family, spike in a particular threat type). For Feodo, use `total_online` for the active C2 count and `new_in_window` for newly discovered C2s in this window; use `malware_counts` to name the dominant families.
- **AlienVault OTX** — one bullet per pulse: pulse name, adversary (if known), targeted countries/industries.
- Sources with `status: "skipped"` or `status: "error"` — mention briefly in a single parenthetical note, do not give them a full section. **Do not generate, infer, or fabricate any data for these sources.**
- IoC values (IPs, URLs, domains) are already defanged in the payload; reproduce them exactly as shown.
- **Only use data that is explicitly present in the payload.** Never invent CVE IDs, vulnerability descriptions, IP addresses, malware names, or any other values.
- Do **not** editorialize or add remediation advice beyond what the source data provides.
- Write in a neutral, factual tone suitable for an executive briefing.

**Under `Attention`**, flag only:
- Any KEV entry where `ransomware` is `true`
- Any CVE with CVSS score ≥ 9.5
- Any single malware family with 10 or more IoCs across ThreatFox or Feodo entries
- Any OTX pulse targeting the Finance industry

If none of these conditions apply, omit the `Attention` line entirely.

**Output format (use exactly this markdown structure):**

### :satellite: Threat Intel
_<one-line headline with aggregate counts>_

- :rotating_light: <CISA KEV entry: CVE, vendor/product, description, ransomware flag>
- :red_circle: <NVD CVE: CVE ID, CVSS score, severity, description>
- :spider_web: URLhaus: <volume + notable clusters>
- :spider_web: ThreatFox: <volume + notable clusters> *(or omit if skipped/error)*
- :computer: Feodo: <volume + notable clusters> *(or omit if skipped/error)*
- :satellite: OTX: <pulse name — adversary, countries, industries> *(or omit if skipped/error)*

:rotating_light: **Attention:** <only if a trigger condition above is met>
