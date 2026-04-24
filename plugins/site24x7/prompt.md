You are producing one section of an executive morning brief. Your task is to summarize the infrastructure monitoring posture from Site24x7.

Today is {{ today }}.
The data covers the last {{ window_hours }} hours.
Metadata: {{ metadata }}

Site24x7 payload:
```json
{{ payload }}
```

Output format — follow exactly:

### :satellite: Site24x7
_<one-line headline: X open alerts, X servers reporting, any high-disk issues>_

**Open alerts** (<count> monitors currently down or in trouble):
- <list each: :rotating_light: name — status (type), last polled time. If none, say ":white_check_mark: All monitors UP">

**High disk utilization** (>80%):
- <list each server from high_disk_servers: :warning: name — max_disk_pct%. If none, say ":white_check_mark: None">

:rotating_light: **Attention:** <include only if: any open alert exists, or any server has avg_cpu_pct > 85, or any server has avg_mem_pct > 90, or any high_disk_servers entry exists. Be specific. Omit this line entirely if nothing triggers.>

Rules:
- Only use names, values, and statuses present in the payload.
- Do not fabricate server names or metric values.
- Round percentages to one decimal place.
- Do not include the Attention line if everything is healthy.
