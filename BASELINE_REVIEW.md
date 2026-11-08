# Presidio baseline: first local review

Run date: 2026-11-07. These observations describe the pinned baseline, not an
accuracy evaluation or approval to send the full CSV to an LLM. No real response
text, respondent IDs, names, or contact details are included in this document.

## Preservation and processing

The real output was checked against the input field by field:

- 1,299 data rows and 20 columns, with the original headers and row order.
- Every non-comment field is identical, including IDs and language labels.
- Empty and whitespace-only comments are identical.
- All 2,598 review records align with the source record, original ID, and field.
- The calling-likelihood field still has 293 recorded scores, 1,006 blanks, and
  four valid zeros.
- SHA-256 checks confirmed both the source CSV and workbook are unchanged.
- Source files and all generated files are ignored by Git under `private_data/`.

| Routing language | Records | Changed comments | Unchanged nonblank | Blank |
| --- | ---: | ---: | ---: | ---: |
| English | 1,280 | 135 | 1,549 | 876 |
| Spanish | 19 | 1 | 29 | 8 |
| Total | 1,299 | 136 | 1,578 | 884 |

The engine scanned 1,714 nonblank comments and returned 160 detections: 83
`PERSON`, 41 `DATE_TIME`, 26 `LOCATION`, four `NRP`, three `PHONE_NUMBER`, and
one each of `URL`, `US_BANK_NUMBER`, and `US_DRIVER_LICENSE`. These are model
labels, not verified identities or confirmed sensitive values. Overlapping
detections can refer to the same text. Detection counts are not accuracy.

The exact runtime versions are in `private_data/survey_presidio.summary.json`.
The run used Presidio Analyzer/Anonymizer 2.2.366, spaCy 3.8.11, and English and
Spanish large models 3.8.0 on the CPU.

## Synthetic checks

Twenty fictional English and Spanish examples exercised names (including short
names and initials), emails, phone numbers, addresses, schools, organizations,
contextual identifiers, and harmless survey feedback. The integration test
blocked DNS/socket connections, model downloads, and GPU activation successfully.

- The selected name, email, and phone targets were covered in both languages.
  This small, straightforward set does not establish general name coverage.
- The English street address was covered. The Spanish street-address example
  left the house number behind after replacing the street name.
- The school examples were covered as `LOCATION`. Both organization examples
  were missed. Presidio's stock NER ignore list excludes `ORGANIZATION`, so
  organization and school coverage depends on how the model labels the phrase.
- Both contextual-identifier examples were missed. A unique role or combination
  of facts can identify someone without looking like a conventional PII entity.
- One of three harmless examples changed: useful timing/duration feedback was
  replaced by `DATE_TIME` placeholders. The two simple 988 examples were retained.

Across the twenty explicitly marked synthetic targets, fifteen were fully
covered, one partly covered, and four missed. These character-span checks are
diagnostic observations, not representative precision/recall or anonymization
metrics. The detailed synthetic-only report is stored in
`private_data/presidio_synthetic_review.json`.

## Real comment spot-check

A reproducible sample (Python random seed 988) selected ten changed and ten
unchanged nonblank comments routed as English. All thirty nonblank comments
routed as Spanish were also inspected. The fifty selected original/redacted
pairs are retained locally in `private_data/survey_presidio.spotcheck.csv`.
Review displays masked possible identifying strings; no identifying excerpts
are reproduced here.

The strongest issue was language mismatch: eight of the ten changed comments
in the English-routed sample were written in Spanish. At least six of the ten
changed comments had clearly unnecessary removals, including ordinary Spanish
words, a service-availability expression, and a relative training date. Other
cases need closer review before labeling them correct or incorrect. Some
Spanish-labeled comments also contained English or mixed-language text.

The ten unchanged English-routed comments mostly concerned access to help,
service functions, and requests for training detail. The thirty Spanish-routed
comments included twenty-nine unchanged comments and one changed comment. No
obvious contact-format strings were observed in that Spanish set. Unchanged
text and absence of obvious contact strings do not establish absence of names
or contextual identifiers. The single Spanish redaction was not adjudicated as
a confirmed identifier.

## Candidates for the next iteration

1. Validate the written language per comment and flag conflicts with the source
   language field, including mixed-language responses. The baseline deliberately
   keeps the approved field-based routing and preserves the original metadata.
2. Build a larger locally labeled set of names, misspellings, initials,
   school/organization references, and contextual identifiers. Include both
   changed and unchanged comments so missed identifiers are visible.
3. Review `DATE_TIME`, `NRP`, and broad location/name detections for loss of useful
   survey content. Measure unnecessary redactions alongside detection misses.
4. Test complete address coverage and domain-specific recognizers. Evaluate any
   allowlist for public program terms, including 988, with regression examples.
5. Decide which metadata and comment context can leave the local environment
   before building LLM inputs. The full CSV retains original IDs, dates, and
   geography; the review CSV retains raw responses.

Custom rules, allowlists, automatic language detection, GLiNER, and LLM calls
have not been added to this baseline.
