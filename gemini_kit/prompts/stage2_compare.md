# Task: compare your conclusions with the human analysts'

Earlier you analyzed this data independently. Your findings are below as **AI findings**. A team of human analysts, working with traditional statistical methods (cleaning, cross-tabulation, bootstrap confidence intervals, rank correlations, keyword coding of open text), reached the conclusions below as **Human findings**, including a table of gaps with current values and proposed targets.

Compare the two sets honestly. You are not trying to agree.

If the AI findings show `appeared_in_runs`, the independent analysis was run several times: give more weight to findings that appeared in every run, and treat one-off findings with caution. `recurring_findings_missing_from_this_run` lists findings that came up in other runs but not in the one shown.

Produce:

1. **agreements**: conclusions both reached. For each, say whether the two sets of evidence are the same or independent (independent agreement is stronger).
2. **disagreements**: where the two differ in substance, size, confidence or interpretation. For each, state which view the data supports better and why, citing table values.
3. **missed_by_humans**: things your analysis found that the human findings do not mention.
4. **missed_by_ai**: things the human findings include that your analysis missed or got wrong.
5. **target_review**: for each human target in the gaps table, say whether it is realistic given the data (too low, about right, too ambitious) and why.
6. **overall_assessment**: three to five sentences on how far a judge should trust the combined conclusions, and the single most important next step.

The same citation rules apply: every number you use must be cited with dataset, row, column and value.
