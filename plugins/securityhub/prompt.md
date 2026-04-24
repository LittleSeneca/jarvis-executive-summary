You are producing the security posture section of an executive morning brief. The data below is a snapshot of active AWS SecurityHub findings updated in the last {{ window_hours }} hours (as of {{ today }}).

Metadata: {{ metadata }}

**Payload:**
```json
{{ payload }}
```

**Instructions:**
- Lead with the full severity counts from counts_by_severity (CRITICAL, HIGH, MEDIUM, LOW, INFORMATIONAL).
- The findings list contains only CRITICAL and HIGH findings — analyse these in detail.
- Highlight any CRITICAL findings or findings that touch IAM resources or public-facing services — name the specific resource type and what the finding is.
- Call out any finding involving public access, overly permissive IAM roles, or open security groups.
- For obvious remediations (e.g. "rotate credentials", "restrict S3 bucket ACL", "enable MFA"), include a one-line pointer.
- Group bullets by severity (CRITICAL → HIGH).
- Do not include a count summary line for MEDIUM/LOW/INFORMATIONAL — those counts appear in the severity table below.
- Be concise: one bullet per distinct issue, not one per finding.
- Under **Attention**, flag any CRITICAL finding or IAM/public-access issue that needs same-day action. Omit the Attention line entirely if no CRITICAL or IAM/public issues exist.
- Do not editorialize beyond what is in the payload.

**Output format (use exactly this markdown structure):**

### :shield: AWS SecurityHub
_<one-line headline: total findings, most severe issue>_

- :red_circle: <CRITICAL finding summary — resource type, remediation pointer if obvious>
- :large_orange_circle: <HIGH finding summary>
- ...
- <one line for MEDIUM/LOW/INFORMATIONAL counts>

:rotating_light: **Attention:** <only if CRITICAL findings or IAM/public-access issues present — otherwise omit>
