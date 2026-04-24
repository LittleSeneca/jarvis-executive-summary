You are producing the cloud spending section of an executive morning brief. The data below comes from AWS Cost Explorer (as of {{ today }}).

Metadata: {{ metadata }}

**Payload:**
```json
{{ payload }}
```

**Instructions:**
- Report today's spend, month-to-date total, and quarter-to-date total.
- Compare MTD to the same period last month: is spend pacing above or below? By how much ($ and %)?
- Compare QTD to the same elapsed days last quarter.
- If month-end or quarter-end forecasts are available, include them.
- Call out the top 3 services driving the current month's bill.
- Flag any service showing an unusual spike vs. the MTD trend.
- Be numerically precise — do not round or paraphrase dollar figures.
- Use the currency from the metadata (default USD).
- Under **Attention**, flag only if MTD is tracking more than 15% above prior month, or if any single-day spend looks anomalous. Omit the Attention line entirely otherwise.

**Output format (use exactly this markdown structure):**

### AWS Billing
_<one-line headline: today's spend and MTD pacing vs prior month>_

- Today: $<today.total> (<date>)
- MTD: $<mtd.total> vs $<prior_mtd> prior month (<pct_delta>% delta)
- QTD: $<qtd.total> vs $<prior_qtd_sameperiod> same-period last quarter (<pct_delta>% delta)
- Forecast: month-end $<forecast.month_end>, quarter-end $<forecast.quarter_end>
- Top services (MTD): <service 1> $<amount>, <service 2> $<amount>, <service 3> $<amount>

**Attention:** <only if MTD >15% above prior or anomalous daily spike — otherwise omit>
