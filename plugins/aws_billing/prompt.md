You are producing the cloud spending section of an executive morning brief. The data below comes from AWS Cost Explorer (as of {{ today }}).

Metadata: {{ metadata }}

**Payload:**
```json
{{ payload }}
```

**Instructions:**
- Report yesterday's total spend. Do NOT list individual services — a formatted table of top services will be appended automatically.
- Report month-to-date and quarter-to-date totals.
- Compare MTD to the same period last month: is spend pacing above or below? By how much ($ and %)?
- Compare QTD to the same elapsed days last quarter.
- If month-end or quarter-end forecasts are available, include them.
- Flag any service showing an unusual spike vs. the MTD trend.
- Be numerically precise — do not round or paraphrase dollar figures.
- Use the currency from the metadata (default USD).
- Under **Attention**, flag only if MTD is tracking more than 15% above prior month, or if yesterday's spend looks anomalous. Omit the Attention line entirely otherwise.

**Output format (use exactly this markdown structure):**

### :moneybag: AWS Billing
_<one-line headline: yesterday's spend and MTD pacing vs prior month — bold the dollar amounts and delta %>_

- Yesterday (**<date>**): **$<yesterday.total>**

- MTD: **$<mtd.total>** vs $<prior_mtd> prior month (**<pct_delta>%** delta)
- QTD: **$<qtd.total>** vs $<prior_qtd_sameperiod> same-period last quarter (**<pct_delta>%** delta)
- Forecast: month-end **$<forecast.month_end>**, quarter-end **$<forecast.quarter_end>**

:rotating_light: **Attention:** <only if MTD >15% above prior or anomalous daily spend — bold the specific amount and % that triggered it — otherwise omit>
