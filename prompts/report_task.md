# Output rules the app checks before showing your report

This call replaces the survey description above: the only data for this report is the payload below (one dataset_key, one audience). Do not use any numbers from the background section.

1. `summary`: two to four short findings. Each lists the IDs it relies on: quantitative `evidence_id`, theme `theme_id`, or `comment_evidence_id`.
2. Every number in a summary finding must come from one of the records it cites (`value`, `display_value`, `numerator_or_score_sum`, `valid_denominator`, `audience_total`, a theme `count`, `reviewed_denominator` or `percent_of_reviewed`), or be the difference between two of them. Write percentages as `display_value` shows them. A finding with any other number is rejected and the whole report is discarded. "988" and "911" are names, not numbers.
3. `proposed_recommendations`: one to three, most important first. Each must set `action_id` to one of the eligible actions listed below. Do not invent an action. If none fits well, choose the closest and say so in `uncertainty`.
4. `limitations`: at least one item must say the before/after ratings are retrospective self-report and that the evidence is descriptive, not causal.

Catalog threshold fields describe proposed rules; the application checks catalog membership
but does not automatically evaluate those thresholds. Do not claim a threshold was met
without the current evidence supporting that comparison. Treat numerical validation as a
consistency check, not proof that an interpretation or recommendation is correct.
