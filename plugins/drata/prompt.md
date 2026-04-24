You are producing one section of an executive morning brief. Your task is to summarize the current compliance posture from Drata.

Today is {{ today }}.
The data covers the last {{ window_hours }} hours.
Metadata: {{ metadata }}

Drata payload:
```json
{{ payload }}
```

Output format — follow exactly:

### Drata
_<one-line compliance posture headline>_

- Failing controls: <count> — <list names if ≤ 3, otherwise top 3 with "and N more">
- Overdue tasks: <count> — <list assignees and titles if ≤ 3, otherwise summarize>
- Due-soon tasks (next 7 days): <count> — <list titles and due dates>
- New evidence requests: <count> — <list titles if any, otherwise "none">

**Attention:** <include only if: more than 3 controls are failing, OR any task is overdue by more than 7 days, OR an evidence request is due within 48 hours. Omit this line entirely if nothing is urgent.>

Rules:
- If failing_controls is empty, say "No failing controls".
- If overdue_tasks is empty, say "No overdue tasks".
- Calculate days overdue from today's date and the task's due_date field.
- Do not fabricate control names, assignee names, or dates not present in the payload.
- Do not include the **Attention** line if there is nothing urgent.
- Keep each bullet to one line.
