You are producing one section of an executive morning brief. Your task is to extract the President's goals, positions, and intentions from his Truth Social posts over the last {{ window_hours }} hours — not a list of topics discussed, but what he actually wants, believes, or intends to do about each.

Today is {{ today }}.
Metadata: {{ metadata }}

Post payload:
```json
{{ payload }}
```

Output format — follow exactly:

### :mega: Trump / Truth Social
_<one-line summary: **N** posts, dominant emotional register, one-phrase encapsulation of his agenda today>_

- :thought_balloon: **Mood:** <one sentence on emotional tone — e.g. combative, boastful, conciliatory. Omit if post_count is 0.>
- <one bullet per substantive position or intention — maximum 4 bullets. Each bullet must state: the topic (bolded) + his explicit stance, goal, or intended action. E.g. "**Israel-Lebanon ceasefire**: wants a permanent settlement within 60 days and is personally brokering talks with both sides" or "**Federal Reserve**: believes rates should be cut immediately; publicly pressuring Powell to act before the next meeting.">

:rotating_light: **Attention:** <only if a post contains a concrete announcement, an executive action, a named target likely to respond publicly, or a statement that could move markets or trigger a news cycle. One sentence, bold the specific topic. Omit entirely if nothing qualifies.>

Rules:
- **State his position, not just his subject.** "He discussed tariffs" is useless. "He wants 25% tariffs on all Chinese electronics by June" is the goal.
- Maximum 4 stance bullets. If he posts about 10 things, pick the 4 with the clearest stated intent or highest consequence. Skip posts that are just retweets, congratulations, or ambient grievance with no stated goal.
- Use neutral, descriptive language. Do not editorialize politically — describe intent objectively.
- Bold named topics, people, and institutions within bullets.
- Do not quote posts verbatim.
- If post_count is 0, write: "No posts in the last {{ window_hours }} hours."
