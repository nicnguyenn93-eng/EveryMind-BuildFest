# Alignment with the supplied BuildFest brief

Sources reviewed locally: `BuildFest (7).pdf` (PDF pages 7-14) and `BuildFest_EveryMind_Survey_Data_FULL.xlsx`, `Survey Data`. Neither source file nor its real responses is included in this repository. The task is to derive usable, evidence-based training improvements from the supplied data, not from invented example findings.

## Official brief versus implementation choices

| Brief requirement | Current coverage / work remaining |
|---|---|
| Accurately process the provided dataset and reasonable updates (PDF page 10) | Actual-export importer and export-shaped synthetic fixtures now work. UI and metrics integration remain. |
| Analyze knowledge changes, behavioral intent, and differences across participant groups (pages 7, 9) | Raw fields and role sets are preserved; production comparisons and paired calculations remain. |
| Reproducibility, sample sizes, small groups, data inconsistencies, open comments, retrospective-rating limitations (pages 13-14) | Missing/unmapped import status and synthetic review contracts exist. Downstream privacy, reviewed search, disclosures, and release checks remain. |
| Practical recommendations and implementation/impact measures (pages 9, 14) | Synthetic report illustrates the contract; real evidence-based action selection remains. |
| Five deliverables: technical artifact, demo up to 120 seconds, 1-2 page memo, one-page AI appendix, PPTX (pages 10-12) | Runnable scaffold and setup instructions exist; final artifacts are unfinished. |
| Document AI tools, prompts, revisions, errors/limitations, and independent validation (page 11) | Record actual work and verification; do not claim simulated approvals or template output were real model runs. |
| Anonymous deliverables/links and accessible submission resources (page 12) | Final packaging/access review remains; the development GitHub URL includes an account identity and is not an anonymous judging link. |

Streamlit, a ten-person minimum, reviewed paraphrase search, executive PDFs, and live-provider report generation are team playbook choices. The brief permits multiple artifact types and does not specifically mandate a runtime LLM call. These choices remain the team's agreed build scope rather than additional official requirements.

## Export mapping

`export_columns.json` contains all 20 exact source headers, including nonbreaking spaces. Matching ignores case and repeated/leading/trailing whitespace, and uses names rather than column position. The raw export puts current knowledge before recalled knowledge. Internally the fields remain paired as:

| Topic | Recalled before | Current/post |
|---|---|---|
| Identify challenges/crises | q1_knowledge | q2_knowledge |
| Describe 988/how it works | q3_knowledge | q4_knowledge |
| Know when to use 988 | q5_knowledge | q6_knowledge |

Roles are multi-select, not mutually exclusive. The original labels include `School staff member` and trailing semicolons; normalized membership uses `School staff`. The agreement midpoint is `Neither agree nor disagree`. Unrecognized presenter labels are audited without guessing their meaning. The importer preserves training-affiliated county but does not yet reconcile county aliases. No retention outcome or causal effect can be inferred from this retrospective survey alone.

## Local source verification

After implementing the adapter, a local read-only check reproduced the following aggregate totals from the supplied workbook. These are code checks by the implementing assistant, not the playbook's independent teammate/Excel signoff.

| Check | Observed |
|---|---|
| Unique responses / duplicate IDs | 1,299 / 0 |
| Selected Student membership | 1,080 |
| Identify challenges agreement, recalled/current | 938 / 1,168; 1,299 valid pairs |
| Explain 988 agreement, recalled/current | 604 / 1,175; 1,299 valid pairs |
| Know when to use 988 agreement, recalled/current | 723 / 1,199; 1,299 valid pairs |
| Valid 0-10 call-intent answers | 293 |
| Equivalent CSV vs XLSX | Identical normalized structural records and dataset keys |

The real workbook stays on the operator's machine. Shared tests use synthetic records only. K3's receiving review by Roles 2-4 remains pending, and these import checks do not establish that the current UI, PDF, privacy protection, or full release is complete.
