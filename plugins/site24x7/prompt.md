You are producing one section of an executive morning brief. Your task is to summarize the infrastructure monitoring posture from Site24x7.

Today is {{ today }}.
The data covers the last {{ window_hours }} hours.
Metadata: {{ metadata }}

Site24x7 payload:
```json
{{ payload }}
```

Output format — follow exactly:

### Site24x7
_<one-line headline: overall infrastructure health and any standout issue>_

- Alerts (last {{ window_hours }}h): <count> — <list monitor names and alert types if ≤ 3, otherwise summarize top issues>
- Currently down: <count monitors> — <list names and types, or "None" if empty>
- SLA at risk: <count> — <list monitor name, current vs target availability, breached status, or "None" if empty>

**Attention:** <include only if: any monitor is currently DOWN, or any SLA is breached. Omit this line entirely if everything is healthy.>

Rules:
- If alerts is empty, say "No alerts in the window".
- If down_monitors is empty, say "None currently down".
- If sla_at_risk is empty, say "No SLA breaches or risks".
- For SLA entries, show availability as a percentage (e.g. 99.1%) and note if breached=true.
- Do not fabricate monitor names, availability figures, or dates not present in the payload.
- Do not include the **Attention** line if everything is healthy.
- Keep each bullet to one or two lines.
