# Worked examples (format and reasoning only)

The two examples below come from a **fictional** CPR-awareness training survey, not from the data you are analyzing. They show the level of care, the citation format and the confidence calibration expected. Their tables start with `example_` and do not exist in your data: never cite them. Do not reuse their topics, numbers or conclusions; reach your own from the real tables.

## Fictional tables used in the examples

```csv
## Table: example_satisfaction
kind,group,n,nps
role,Student,640,4.0
role,Teacher,85,71.8
county,North,420,12.5
county,South,305,48.2

## Table: example_county_mix
county,n,student_pct
North,420,96.0
South,305,64.6

## Table: example_confidence_by_group
dimension,group,n,pct_would_act
audience,Student,48,52.1
audience,Adult,14,92.9
```

## Example 1: a composition effect, moderate confidence

```json
{
  "id": "F3",
  "title": "The county gap mostly reflects who attended",
  "category": "group_difference",
  "statement": "South looks far more satisfied than North (NPS 48.2 vs 12.5), but North's audience was almost entirely students (96.0%) compared with 64.6% in South, and students rate the training much lower than teachers everywhere (4.0 vs 71.8). Most of the county gap is therefore a difference in audience, not in how the training was delivered.",
  "evidence": [
    {"dataset": "example_satisfaction", "row": [{"column": "group", "value": "South"}], "column": "nps", "value": "48.2", "meaning": "NPS in South county"},
    {"dataset": "example_satisfaction", "row": [{"column": "group", "value": "North"}], "column": "nps", "value": "12.5", "meaning": "NPS in North county"},
    {"dataset": "example_county_mix", "row": [{"column": "county", "value": "North"}], "column": "student_pct", "value": "96.0", "meaning": "Share of North respondents who were students"},
    {"dataset": "example_county_mix", "row": [{"column": "county", "value": "South"}], "column": "student_pct", "value": "64.6", "meaning": "Share of South respondents who were students"},
    {"dataset": "example_satisfaction", "row": [{"column": "group", "value": "Student"}], "column": "nps", "value": "4.0", "meaning": "NPS among students"},
    {"dataset": "example_satisfaction", "row": [{"column": "group", "value": "Teacher"}], "column": "nps", "value": "71.8", "meaning": "NPS among teachers"}
  ],
  "derivation": "County gap = 48.2 - 12.5 = 35.7 NPS points. Student share differs by 96.0 - 64.6 = 31.4 percentage points.",
  "framework": "Simpson's paradox / confounding by audience composition",
  "confidence": "moderate",
  "confidence_reason": "Both groups are large (n = 420 and 305) and the direction is clear, but no table gives NPS for students within each county, so how much of the gap remains after accounting for audience cannot be measured directly.",
  "caveats": "A within-county, within-audience comparison is needed to confirm. Sessions were not randomly assigned to counties."
}
```

Note what the example does: it cites every number it uses, shows the arithmetic, names the framework only because it explains the pattern, and sets confidence by what the tables can and cannot show.

## Example 2: a tempting claim held to low confidence

```json
{
  "id": "F6",
  "title": "Adults may be more willing to act, but the sample is too small to say",
  "category": "behavioral_intent_gap",
  "statement": "Among people asked whether they would act in an emergency, 92.9% of adults said yes against 52.1% of students. The direction fits what is known about adolescent help-seeking, but only 14 adults answered, so the size of the gap is very uncertain.",
  "evidence": [
    {"dataset": "example_confidence_by_group", "row": [{"column": "group", "value": "Adult"}], "column": "pct_would_act", "value": "92.9", "meaning": "Adults who would act"},
    {"dataset": "example_confidence_by_group", "row": [{"column": "group", "value": "Adult"}], "column": "n", "value": "14", "meaning": "Adults asked"},
    {"dataset": "example_confidence_by_group", "row": [{"column": "group", "value": "Student"}], "column": "pct_would_act", "value": "52.1", "meaning": "Students who would act"},
    {"dataset": "example_confidence_by_group", "row": [{"column": "group", "value": "Student"}], "column": "n", "value": "48", "meaning": "Students asked"}
  ],
  "derivation": null,
  "framework": "Intention-behavior gap; adolescent help-seeking barriers",
  "confidence": "low",
  "confidence_reason": "Only 14 adults and 48 students were asked; one or two answers change the adult percentage by 7 points or more.",
  "caveats": "Self-reported intention right after training, not behavior. The question was on only some survey versions, so the people asked may differ from those not asked."
}
```

Note what the example does: it reports an interesting difference but refuses to overstate it, explains exactly why confidence is low, and says what the data does not measure.

## Example 3: a recommendation tied to a finding

```json
{
  "id": "R2",
  "action": "Add a three-minute hands-on practice round to student sessions, run in pairs, before the closing summary.",
  "addresses": ["F3", "F6"],
  "why_it_should_work": "Practice builds perceived behavioral control (self-efficacy), which predicts intention to act more strongly than knowledge alone; students also rate passive sessions lowest.",
  "effort": "low",
  "indicator": "Student NPS and % of students who would act",
  "current_value": "Student NPS 4.0",
  "target": "Student NPS of 20 or higher within two quarters"
}
```
