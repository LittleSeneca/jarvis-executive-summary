You are producing one section of an executive morning brief. Your task is to summarize the weather for today and tomorrow in plain, concise language.

Today is {{ today }}.
The data covers the next {{ window_hours }} hours.
Metadata: {{ metadata }}

Weather payload:
```json
{{ payload }}
```

Output format — follow exactly:

### Weather
_<one-line current conditions and today's outlook>_

- Current: <temp>°, feels like <feels_like>°, <conditions>, humidity <humidity>%, wind <wind> <wind_unit>
- Today: high <high>° / low <low>°, <precip_chance_pct>% chance of precipitation — <summary>
- Tomorrow: high <high>° / low <low>°, <precip_chance_pct>% chance of precipitation — <summary>

**Attention:** <include only if there is something genuinely actionable: heavy rain, severe weather, heat warning, hard freeze, dangerous wind. Omit this line entirely if conditions are routine.>

Rules:
- Keep the headline to one sentence.
- Lead with anything actionable (severe weather, freeze, flood risk) before routine conditions.
- Convert precip_chance decimal (0.75) to a percentage (75%).
- Use the unit labels from the payload (F/C, mph/m/s).
- Do not add commentary, opinions, or context beyond what is in the payload.
- Do not include the **Attention** line if there is nothing notable.
