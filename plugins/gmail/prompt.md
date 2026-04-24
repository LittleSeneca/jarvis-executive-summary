You are producing one section of an executive morning brief. Your task is to summarize the Gmail inbox activity for the period covered.

Today is {{ today }}.
The data covers the last {{ window_hours }} hours.
Metadata: {{ metadata }}

Gmail payload:
```json
{{ payload }}
```

Output format — follow exactly:

### Gmail
_<one-line headline summarizing inbox volume and anything standout>_

- <Theme or sender group>: <brief summary of messages, noting any requiring a response>
- <repeat per theme/thread cluster — group related messages together where it helps readability>

**Attention:** <include only if: any message appears to need an urgent response, a time-sensitive deadline is mentioned, or a human (non-automated) sender is waiting. Omit this line entirely if nothing needs immediate action.>

Rules:
- Summarize every message in the payload — do not filter or skip any.
- Group by theme, sender, or thread when it reduces noise (e.g., "3 GitHub notifications", "2 messages from Alice about the Q2 budget").
- Distinguish human-initiated messages from automated/system messages.
- Note any message with is_unread=true that appears to need a reply.
- Note any message with has_attachments=true if the attachment seems relevant.
- Do not fabricate subject lines, sender names, or content not present in the payload.
- Do not include the **Attention** line if nothing needs immediate action.
- Keep each bullet to one or two lines.
- If message_count is 0, say "No new messages in the inbox window."
