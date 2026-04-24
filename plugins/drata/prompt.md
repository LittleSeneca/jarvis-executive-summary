You are producing one section of an executive morning brief. Your task is to summarize the current compliance posture from Drata.

Today is {{ today }}.
Metadata: {{ metadata }}

Drata payload:
```json
{{ payload }}
```

Output format — follow exactly:

### :shield: Drata
_<one-line headline: **X** of **Y** monitors failing, **Z** unhealthy personnel>_

**Monitors** (**<total>** total — <by_status breakdown, e.g. "**8 FAILED**, 110 PASSED, 2 PENDING">):
*(Failed monitor details are shown in the table below — do not list them individually here)*
- Summarise in one sentence what the HIGH-priority failures relate to (e.g. "**2 HIGH**-priority failures: **email uniqueness** and **MFA**"). If none failed, say ":white_check_mark: All monitors passing".

**Unhealthy personnel** (**<count>** current employees/contractors):
- :bust_in_silhouette: **<name>** — <failing_checks (human-readable, one line each, up to 10; if more say "and N more")>
- If none, say ":white_check_mark: No unhealthy personnel"

:rotating_light: **Attention:** <include only if: any HIGH-priority FAILED monitor exists, or unhealthy personnel count > 0. Be specific — bold the monitor name or person name. Omit this line entirely if nothing triggers.>

Rules:
- Only use names, descriptions, and counts that are present in the payload.
- Do not fabricate monitor names, personnel names, or check names.
- Keep bullets concise — one line per item.
- For failing_checks, convert type codes to readable names where obvious (e.g. IDENTITY_MFA → MFA, SECURITY_TRAINING → Security Training, ACCEPTED_POLICIES → Policy Acknowledgment).
