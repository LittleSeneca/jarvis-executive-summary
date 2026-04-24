You are producing one section of an executive morning brief. Your task is to analyse the mood, priorities, and focus areas of the President of the United States based on his Truth Social posts over the last {{ window_hours }} hours.

Today is {{ today }}.
Metadata: {{ metadata }}

Post payload:
```json
{{ payload }}
```

Output format — follow exactly:

### :mega: Trump / Truth Social
_<one-line summary: how many posts, overall mood/energy level, and dominant theme>_

- :thought_balloon: **Mood:** <one sentence characterising the overall emotional tone — e.g. combative, celebratory, anxious, confident, grievance-focused>
- :pushpin: **Top priorities:** <2–3 sentence summary of what topics are consuming the most attention, ranked by post volume and intensity>
- :globe_with_meridians: **Foreign policy signals:** <what positions, relationships, or situations abroad are on his mind — omit if nothing substantive>
- :us: **Domestic targets:** <who or what is being criticised or praised domestically — institutions, individuals, policies>
- :bar_chart: **Market/policy relevance:** <any stated or implied positions on trade, regulation, spending, or economic policy that could move markets or affect business>

:rotating_light: **Attention:** <include only if posts contain a concrete announcement, a significant policy shift, or a statement likely to move markets or trigger a news cycle. Be specific. Omit this line entirely if nothing qualifies.>

Rules:
- This is sentiment and intent analysis, not a transcript. Do not quote posts verbatim.
- Describe what he is thinking and feeling, not what he said word-for-word.
- Use neutral, descriptive language. Do not editorialize or characterise tone as positive/negative from a political standpoint — describe the emotional register objectively (e.g. "frustrated," "boastful," "conciliatory").
- Omit any bullet whose topic did not appear in the posts.
- If post_count is 0, write: "No posts in the last {{ window_hours }} hours."
