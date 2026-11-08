"""Current county aggregates; only publishable statistics cross the web boundary."""

import pandas as pd

import analysis
from cleaned_analysis import adapt_cleaned
from report_service import get_analysis


ALL = "(all)"
OTHER = "Other surveyed locations"
COUNTIES = (
    "Allegany", "Anne Arundel", "Baltimore", "Baltimore City", "Calvert", "Caroline",
    "Carroll", "Cecil", "Charles", "Dorchester", "Frederick", "Garrett", "Harford",
    "Howard", "Kent", "Montgomery", "Prince George's", "Queen Anne's", "St. Mary's",
    "Somerset", "Talbot", "Washington", "Wicomico", "Worcester",
)


def release_partition(counts, candidates):
    """Withhold small cells/complements and one extra cell if totals expose them."""
    total = sum(counts.values())
    released = {key for key, n in counts.items() if candidates.get(key, False)
                and n >= analysis.MIN_VALID and not 0 < total - n < analysis.MIN_VALID}
    hidden = sum(n for key, n in counts.items() if key not in released)
    if 0 < hidden < analysis.MIN_VALID and released:
        released.remove(min(released, key=lambda key: (counts[key], key)))
    return released


def family(identifier):
    for key, label in (("IDENTIFY_CHALLENGES", "identify"), ("EXPLAIN_988", "explain"),
                       ("WHEN_988", "when"), ("RECOMMENDATION", "recommendation"), ("INTENT", "intent")):
        if "_" + key + "_" in identifier:
            return label
    return "post_988"


def metric(evidence, suffix):
    return next((row for row in evidence if row["evidence_id"].endswith(suffix)), None)


class Dashboard:
    def __init__(self, export):
        self.export = export
        self.responses, _ = adapt_cleaned(export.data)
        analysis.validate_responses(self.responses)
        self.counties = export.data.county.where(export.data.county.isin(COUNTIES), OTHER)
        self.cache = {}
        # Mutually exclusive display groups keep response rings from double counting.
        self.roles = self.responses.role_membership.map(lambda roles: roles[0] if len(roles) == 1
            else ("Multiple roles" if roles else "Unspecified role"))
        pre = pd.concat([analysis.scores(self.responses, before) for _, before, _, _ in analysis.PAIRS], axis=1)
        post = pd.concat([analysis.scores(self.responses, after) for _, _, after, _ in analysis.PAIRS], axis=1)
        self.gain = post.mean(axis=1) - pre.mean(axis=1)
        self.engaged = analysis.scores(export.data.rename(columns={"presenter_engaged__status": "presenter_engaged_status"}), "presenter_engaged")
        sessions = export.data.get("session_key", pd.Series("", index=export.data.index)).fillna("")
        codes = {key: f"Session {i + 1:03d}" for i, key in enumerate(sorted(set(sessions) - {""}))}
        dates = pd.to_datetime(export.data.get("training_date", pd.Series(None, index=export.data.index, dtype="object")), errors="coerce")
        self.splits = {"session": sessions.map(codes).fillna("Unspecified session"),
            "quarter": dates.dt.to_period("Q").astype(str).replace("NaT", "Unspecified quarter"),
            "language": export.data.get("form_language", pd.Series("unknown", index=export.data.index)).map(
                {"en": "English form", "es": "Spanish form"}).fillna("Unspecified form language")}


    def for_audience(self, audience):
        if audience not in analysis.AUDIENCES:
            raise ValueError("Choose a supported audience.")
        if audience not in self.cache:
            self.cache[audience] = self._build(audience)
        return self.cache[audience]

    def _build(self, audience):
        full = get_analysis(self.export.path, audience)
        selected = analysis.audience_mask(self.responses, audience)
        locations = (*COUNTIES, OTHER)
        masks = {name: self.counties.eq(name) for name in locations}
        counts = {name: int((selected & mask).sum()) for name, mask in masks.items()}
        local = {name: analysis.analyze_data(self.responses.loc[mask], self.export.dataset_key, audience)
                 for name, mask in masks.items()}
        available = release_partition(counts, {name: item["status"] == "available" for name, item in local.items()})
        if full["status"] != "available":
            available = set()

        valid = {}
        for name, before, after, _ in analysis.PAIRS:
            key = {"identify_challenges": "identify", "explain_988": "explain", "when_988": "when"}[name]
            valid[key] = analysis.scores(self.responses, before).notna() & analysis.scores(self.responses, after).notna()
        for key in ("recommendation", "intent"):
            valid[key] = analysis.scores(self.responses, key, 0, 10).notna()
        valid["post_988"] = analysis.scores(self.responses, "q4_knowledge").notna() & analysis.scores(self.responses, "q6_knowledge").notna()
        valid["gain"] = self.gain.notna()
        valid["engagement"] = self.engaged.notna()
        full_families = {family(e["evidence_id"]) for e in full["quantitative_evidence"]}
        full_families.update(key for key in ("gain", "engagement") if analysis.publishable(valid[key], selected))
        families = {}
        for key, values in valid.items():
            numbers = {name: int((values & selected & mask).sum()) for name, mask in masks.items()}
            candidates = {name: name in available and key in full_families
                          and (analysis.publishable(values, selected & masks[name]) if key in ("gain", "engagement")
                               else any(family(e["evidence_id"]) == key for e in local[name]["quantitative_evidence"]))
                          for name in locations}
            families[key] = release_partition(numbers, candidates)

        summaries, cube, options = {}, [], []
        for name in (ALL, *locations):
            is_all = name == ALL
            allowed = full["status"] == "available" if is_all else name in available
            source = full if is_all else local[name]
            evidence = source["quantitative_evidence"] if is_all else [e for e in source["quantitative_evidence"]
                if allowed and name in families[family(e["evidence_id"])]]
            n = int(selected.sum()) if is_all else counts[name]
            sessions = None
            if allowed and "session_key" in self.export.data:
                scope = selected if is_all else selected & masks[name]
                sessions = int(self.export.data.loc[scope, "session_key"].replace("", pd.NA).nunique())
            summaries[name] = dict(county=name, audience=audience,
                status="available" if allowed else "withheld_or_empty", n=n if allowed or n == 0 else None,
                sessions=sessions, quantitative_evidence=evidence, limitations=source["limitations"])
            row = dict(county=name, role=ALL, split_dim="none", split_val="none",
                       n=summaries[name]["n"], sessions=sessions, student_pct=None,
                       reliability=("solid" if n >= 30 else "small sample") if allowed else "withheld")
            for column, suffix in (("mean_recommend", "RECOMMENDATION_MEAN"), ("pct_know_when", "WHEN_988_POST"),
                                   ("call_mean", "INTENT_MEAN")):
                item = metric(evidence, suffix)
                row[column] = item["value"] if item else None
            call = metric(evidence, "INTENT_MEAN")
            row.update(n_call=call["valid_denominator"] if call else None, n_deliv=None,
                       engaged_mean=None, ci_low=None, ci_high=None)
            cube.append(row)
            options.append(dict(key=name, label="All surveyed locations" if is_all else name,
                                n=summaries[name]["n"], available=allowed))
        # Extra frontend metrics retain their actual definitions: NPS is not the
        # recommendation mean, and a 1–5 mean gain is not a percentage-point gain.
        for row in cube:
            scope = selected if row["county"] == ALL else selected & masks[row["county"]]
            extra = self.display_metrics(scope, row["n"] is not None and row["n"] >= analysis.MIN_VALID)
            if row["county"] != ALL and row["county"] not in families["recommendation"]:
                extra["nps"] = None
            if row["county"] != ALL:
                for key, column in (("gain", "gain_index"), ("engagement", "engaged_mean")):
                    if row["county"] not in families[key]:
                        extra[column] = None
            row.update(extra)
        self.add_breakdowns(cube, selected, masks, available)
        return dict(dataset_key=self.export.dataset_key, audience=audience, full_analysis=full,
                    counties=options, summaries=summaries, cube=cube,
                    map_notes=["All retained responses are included; quality flags do not automatically exclude records.",
                               "Small groups, complements, and secondary cells may be withheld; grey does not mean zero.",
                               "NPS uses recommend scores; knowledge gain is the change in mean available 1–5 item scores.",
                               "Rings and breakdowns show publishable groups only; suppressed groups are omitted.",
                               "Gemini reports cover the selected audience across all surveyed locations, regardless of county."])

    def display_metrics(self, scope, allowed):
        def permitted(values):
            return allowed and analysis.publishable(values.notna(), scope)
        recommend = analysis.scores(self.responses, "recommendation", 0, 10)
        nps = None
        if permitted(recommend):
            values = recommend[scope & recommend.notna()]
            nps = float(100 * (values.ge(9).mean() - values.le(6).mean()))
        return dict(nps=nps, ci_low=None, ci_high=None,
            gain_index=float(self.gain[scope].mean()) if permitted(self.gain) else None,
            engaged_mean=float(self.engaged[scope].mean()) if permitted(self.engaged) else None,
            student_pct=None)

    def add_breakdowns(self, cube, selected, masks, available):
        """Safe exclusive-role/period/session slices for the existing explorer.

        Omit an entire finer partition when it contains small nonempty children.
        This avoids exposing a small child's size by subtraction from its parent.
        Session labels are local ordinal labels, never school names or raw keys.
        """
        def row_for(scope, county, role, dim="none", value="none"):
            n = int(scope.sum())
            item = dict(county=county, role=role, split_dim=dim, split_val=value,
                n=n, sessions=None, reliability="solid" if n >= 30 else "small sample",
                mean_recommend=None, pct_know_when=None, call_mean=None, n_call=None, n_deliv=None)
            item.update(self.display_metrics(scope, True))
            for field, dest in (("recommendation", "mean_recommend"), ("intent", "call_mean")):
                values = analysis.scores(self.responses, field, 0, 10)
                if analysis.publishable(values.notna(), scope):
                    item[dest] = float(values[scope].mean())
                    if field == "intent":
                        item["n_call"] = int(values[scope].notna().sum())
            values = analysis.scores(self.responses, "q6_knowledge")
            if analysis.publishable(values.notna(), scope):
                item["pct_know_when"] = float(100 * values[scope & values.notna()].ge(4).mean())
            return item

        for county in (ALL, *sorted(available)):
            scope = selected if county == ALL else selected & masks[county]
            partitions = [(ALL, scope)]
            counts = self.roles[scope].value_counts()
            if len(counts) and counts.ge(analysis.MIN_VALID).all():
                for role in sorted(counts.index):
                    child = scope & self.roles.eq(role)
                    cube.append(row_for(child, county, role))
                    partitions.append((role, child))
            for role, parent in partitions:
                for dimension, labels in self.splits.items():
                    sizes = labels[parent].value_counts()
                    if len(sizes) and sizes.ge(analysis.MIN_VALID).all():
                        for label in sorted(sizes.index):
                            cube.append(row_for(parent & labels.eq(label), county, role, dimension, label))
