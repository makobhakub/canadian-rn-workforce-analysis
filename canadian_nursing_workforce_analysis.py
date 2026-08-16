# -*- coding: utf-8 -*-
"""Registered Nurse Workforce Dynamics Across Canadian Jurisdictions, 2018–2024.

Portfolio analysis using the Canadian Institute for Health Information (CIHI)
Nursing in Canada data tables.

Research questions
------------------
1. How did the composition of RN inflow differ across jurisdictions?
2. How did current-year inflow compare with preceding-year outflow after
   accounting for workforce size?
3. How did the internationally educated share of RN inflow change from 2018
   to 2024?

Method summary
--------------
The 2017 observations are retained only to calculate 2018 longitudinal
metrics. The reporting window is 2018–2024. Missing and suppressed values are
preserved as NaN. Longitudinal measures are calculated only when the preceding
record is the immediately preceding calendar year.
"""

from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


# %% Configuration and data acquisition
DATA_URL = (
    "https://www.cihi.ca/sites/default/files/document/"
    "nursing-in-canada-2016-2025-data-tables-en.xlsx"
)
DATA_FILENAME = "nursing-in-canada-2016-2025-data-tables-en.xlsx"
ANALYSIS_YEARS = list(range(2018, 2025))
BASELINE_YEAR = 2017

PROVINCES = [
    "Newfoundland and Labrador",
    "Prince Edward Island",
    "Nova Scotia",
    "New Brunswick",
    "Quebec",
    "Ontario",
    "Manitoba",
    "Saskatchewan",
    "Alberta",
    "British Columbia",
]
TERRITORIES = ["Yukon", "Northwest Territories/Nunavut"]
JURISDICTIONS = PROVINCES + TERRITORIES

EXPECTED_COMPLETE_SERIES = {
    "British Columbia",
    "New Brunswick",
    "Newfoundland and Labrador",
    "Nova Scotia",
    "Ontario",
    "Quebec",
    "Saskatchewan",
    "Yukon",
}


def get_workbook() -> Path:
    """Return a local CIHI workbook path, downloading it when necessary."""
    colab_path = Path("/content")
    data_dir = colab_path if colab_path.exists() else Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    workbook_path = data_dir / DATA_FILENAME

    if not workbook_path.exists():
        print(f"Downloading CIHI workbook to {workbook_path} ...")
        request = Request(
            DATA_URL,
            headers={"User-Agent": "Mozilla/5.0 (RN workforce portfolio analysis)"},
        )
        try:
            with urlopen(request, timeout=60) as response:
                workbook_path.write_bytes(response.read())
        except (HTTPError, URLError) as error:
            raise RuntimeError(
                "The CIHI workbook could not be downloaded automatically. "
                f"Download {DATA_FILENAME} from {DATA_URL} and place it in "
                f"{data_dir.resolve()}."
            ) from error

    return workbook_path


# %% Load and reshape CIHI Table 4a
workbook_path = get_workbook()

# The Definitions sheet is loaded to keep the analysis tied to CIHI's source
# terminology. Table 4a supplies the observations used below.
definitions = pd.read_excel(workbook_path, sheet_name="Definitions")
raw_4a = pd.read_excel(workbook_path, sheet_name="Table 4a", skiprows=1)

raw_4a.columns.values[:4] = ["nurse_type", "jurisdiction", "category", "group"]
raw_4a["nurse_type"] = raw_4a["nurse_type"].ffill()
raw_4a["jurisdiction"] = raw_4a["jurisdiction"].ffill()

year_columns = [
    column
    for column in raw_4a.columns
    if str(column).strip().isdigit()
    and BASELINE_YEAR <= int(str(column).strip()) <= max(ANALYSIS_YEARS)
]

expected_years = set(range(BASELINE_YEAR, max(ANALYSIS_YEARS) + 1))
found_years = {int(str(column).strip()) for column in year_columns}
if found_years != expected_years:
    raise ValueError(
        f"Expected workbook years {sorted(expected_years)}, found {sorted(found_years)}."
    )

rn_long = raw_4a.loc[
    raw_4a["nurse_type"].eq("Registered nurses"),
    ["jurisdiction", "category", "group", *year_columns],
].melt(
    id_vars=["jurisdiction", "category", "group"],
    value_vars=year_columns,
    var_name="year",
    value_name="value_raw",
)

# CIHI suppression marks and other non-numeric entries become NaN. They are
# never replaced with zero.
rn_long["value"] = pd.to_numeric(
    rn_long["value_raw"]
    .astype("string")
    .str.replace(",", "", regex=False)
    .str.strip(),
    errors="coerce",
)
rn_long["year"] = rn_long["year"].astype(int)

rn_pivot = rn_long.pivot_table(
    index=["jurisdiction", "year"],
    columns=["category", "group"],
    values="value",
    aggfunc="first",
).reset_index()


def flatten_column(column: object) -> str:
    """Convert a scalar or MultiIndex column label to snake case."""
    parts = column if isinstance(column, tuple) else (column,)
    clean_parts = [
        str(part).strip().lower().replace(" ", "_")
        for part in parts
        if str(part).strip() and str(part).strip().lower() != "nan"
    ]
    return "_".join(clean_parts).strip("_")


rn_pivot.columns = [flatten_column(column) for column in rn_pivot.columns]
rn_pivot = rn_pivot.rename(
    columns={
        "workforce_total": "workforce",
        "inflow_canadian_educated": "inflow_domestic",
        "inflow_internationally_educated": "inflow_intl",
        "inflow_grad_location_not_stated": "inflow_not_stated",
        "outflow_total": "outflow",
        "renewal_total": "renewal",
    }
)

required_columns = {
    "jurisdiction",
    "year",
    "workforce",
    "inflow_total",
    "inflow_domestic",
    "inflow_intl",
    "inflow_not_stated",
    "outflow",
    "renewal",
}
missing_columns = required_columns.difference(rn_pivot.columns)
if missing_columns:
    raise KeyError(f"Expected CIHI fields were not found: {sorted(missing_columns)}")


# %% Construct the authoritative analytical dataframe
rn_base = rn_pivot.loc[rn_pivot["jurisdiction"].isin(JURISDICTIONS)].copy()
rn_base["geo_type"] = np.where(
    rn_base["jurisdiction"].isin(PROVINCES), "Province", "Territory"
)
rn_base = rn_base.sort_values(["jurisdiction", "year"]).reset_index(drop=True)

grouped = rn_base.groupby("jurisdiction", sort=False)
rn_base["prev_year"] = grouped["year"].shift(1)
rn_base["prev_workforce"] = grouped["workforce"].shift(1)
rn_base["prev_outflow"] = grouped["outflow"].shift(1)
rn_base["consecutive_year"] = rn_base["year"].sub(rn_base["prev_year"]).eq(1)

rn_base["workforce_change"] = (
    rn_base["workforce"] - rn_base["prev_workforce"]
).where(rn_base["consecutive_year"])
rn_base["net_flow"] = (
    rn_base["inflow_total"] - rn_base["prev_outflow"]
).where(rn_base["consecutive_year"])
rn_base["decomp_discrepancy"] = (
    rn_base["workforce_change"] - rn_base["net_flow"]
)

valid_denominator = rn_base["prev_workforce"].gt(0) & rn_base["consecutive_year"]
rn_base["workforce_growth_pct"] = (
    rn_base["workforce_change"] / rn_base["prev_workforce"] * 100
).where(valid_denominator)
rn_base["inflow_per_1k"] = (
    rn_base["inflow_total"] / rn_base["prev_workforce"] * 1_000
).where(valid_denominator)
rn_base["outflow_churn_per_1k"] = (
    rn_base["prev_outflow"] / rn_base["prev_workforce"] * 1_000
).where(valid_denominator)
rn_base["net_flow_per_1k"] = (
    rn_base["net_flow"] / rn_base["prev_workforce"] * 1_000
).where(valid_denominator)
rn_base["intl_share_pct"] = (
    rn_base["inflow_intl"] / rn_base["inflow_total"] * 100
).where(rn_base["inflow_total"].gt(0))

rn_final = rn_base.loc[rn_base["year"].isin(ANALYSIS_YEARS)].copy()


# %% Validation
component_columns = ["inflow_domestic", "inflow_intl", "inflow_not_stated"]
reconciliation_columns = [*component_columns, "inflow_total"]

rn_final["inflow_validity"] = "Not Verifiable"
verifiable = rn_final[reconciliation_columns].notna().all(axis=1)
reconciles = np.isclose(
    rn_final.loc[verifiable, component_columns].sum(axis=1),
    rn_final.loc[verifiable, "inflow_total"],
)
rn_final.loc[verifiable, "inflow_validity"] = np.where(
    reconciles, "Valid", "Mismatch"
)

duplicate_count = int(
    rn_final.duplicated(subset=["jurisdiction", "year"], keep=False).sum()
)
if duplicate_count:
    raise ValueError(f"Found {duplicate_count} duplicate jurisdiction-year rows.")

inflow_status_counts = (
    rn_final["inflow_validity"]
    .value_counts()
    .reindex(["Valid", "Not Verifiable", "Mismatch"], fill_value=0)
)
if inflow_status_counts["Mismatch"]:
    raise ValueError(
        f"Found {inflow_status_counts['Mismatch']} inflow reconciliation mismatches."
    )

core_metrics = ["workforce", "inflow_total", "renewal", "outflow"]
figure_metrics = [
    *component_columns,
    "intl_share_pct",
    "inflow_per_1k",
    "outflow_churn_per_1k",
]


def has_complete_series(group: pd.DataFrame) -> bool:
    """Require all seven analysis years and all fields used in the figures."""
    window = group.loc[group["year"].isin(ANALYSIS_YEARS)].set_index("year")
    if set(window.index) != set(ANALYSIS_YEARS) or not window.index.is_unique:
        return False
    required = [*core_metrics, *figure_metrics]
    return bool(
        window[required].notna().all().all()
        and window["consecutive_year"].all()
        and window["inflow_validity"].eq("Valid").all()
    )


full_sets = sorted(
    jurisdiction
    for jurisdiction, group in rn_final.groupby("jurisdiction")
    if has_complete_series(group)
)

if set(full_sets) != EXPECTED_COMPLETE_SERIES:
    raise ValueError(
        "The complete-series jurisdictions changed. "
        f"Expected {sorted(EXPECTED_COMPLETE_SERIES)}; found {full_sets}."
    )

continuity_issues = int((~rn_final["consecutive_year"]).sum())
decomp_summary = rn_final["decomp_discrepancy"].abs().agg(["mean", "max"])

print("VALIDATION SUMMARY")
print(f"Duplicate jurisdiction-year rows: {duplicate_count}")
print(f"Rows without an immediately preceding calendar year: {continuity_issues}")
print("Inflow component reconciliation:")
print(inflow_status_counts.to_string())
print(
    "Absolute decomposition discrepancy "
    f"(mean / max): {decomp_summary['mean']:.2f} / {decomp_summary['max']:.2f}"
)
print(f"Complete-series jurisdictions ({len(full_sets)}): {', '.join(full_sets)}")

# The discrepancy is reported as a diagnostic, not treated as an error: annual
# workforce change need not equal the simplified inflow-minus-prior-outflow
# identity because of revisions and other movements captured in the source.


# %% Summary tables used by the figures
plot_df = rn_final.loc[rn_final["jurisdiction"].isin(full_sets)].copy()

inflow_totals = plot_df.groupby("jurisdiction")[reconciliation_columns].sum(
    min_count=len(ANALYSIS_YEARS)
)
inflow_composition = (
    inflow_totals[component_columns]
    .div(inflow_totals["inflow_total"], axis=0)
    .mul(100)
    .sort_values("inflow_intl", ascending=False)
)
inflow_composition.columns = [
    "Canadian educated",
    "Internationally educated",
    "Grad location not stated",
]

growth_summary = (
    plot_df.groupby("jurisdiction")
    .agg(
        avg_annual_growth_pct=("workforce_growth_pct", "mean"),
        inflow_per_1k=("inflow_per_1k", "mean"),
        outflow_churn_per_1k=("outflow_churn_per_1k", "mean"),
        net_flow_per_1k=("net_flow_per_1k", "mean"),
    )
    .sort_values("avg_annual_growth_pct", ascending=False)
)

share_table = plot_df.pivot(
    index="jurisdiction", columns="year", values="intl_share_pct"
)
share_change = pd.DataFrame(
    {
        "2018 share (%)": share_table[2018],
        "2024 share (%)": share_table[2024],
    }
)
share_change["change (percentage points)"] = (
    share_change["2024 share (%)"] - share_change["2018 share (%)"]
)
share_change = share_change.sort_values(
    "change (percentage points)", ascending=False
)

print("\nAGGREGATE INFLOW COMPOSITION, 2018–2024 (%)")
print(inflow_composition.round(2).to_string())
print("\nAVERAGE ANNUAL WORKFORCE DYNAMICS, 2018–2024")
print(growth_summary.round(2).to_string())
print("\nCHANGE IN INTERNATIONALLY EDUCATED SHARE, 2018–2024")
print(share_change.round(2).to_string())


# %% Figure 1: aggregate inflow composition
sns.set_theme(style="whitegrid")
figure_1, axis_1 = plt.subplots(figsize=(12, 7))
inflow_composition.plot(
    kind="bar",
    stacked=True,
    width=0.75,
    color=["#2F6B9A", "#E07A2D", "#8A8A8A"],
    ax=axis_1,
)
axis_1.set(
    title="RN Inflow Composition by Jurisdiction, 2018–2024",
    xlabel="Jurisdiction (sorted by internationally educated share)",
    ylabel="Percentage of total RN inflow (%)",
    ylim=(0, 100),
)
axis_1.legend(title="Education location", bbox_to_anchor=(1.02, 1), loc="upper left")
axis_1.tick_params(axis="x", rotation=45)
for label in axis_1.get_xticklabels():
    label.set_horizontalalignment("right")
figure_1.tight_layout()
plt.show()


# %% Figure 2: inflow intensity versus preceding-year outflow churn
figure_2, axis_2 = plt.subplots(figsize=(9, 9))
axis_2.scatter(
    growth_summary["outflow_churn_per_1k"],
    growth_summary["inflow_per_1k"],
    s=120,
    color="#2F6B9A",
    edgecolor="black",
    alpha=0.85,
)

axis_limit = float(
    np.ceil(
        max(
            growth_summary["outflow_churn_per_1k"].max(),
            growth_summary["inflow_per_1k"].max(),
        )
        / 10
    )
    * 10
    + 10
)
axis_2.plot(
    [0, axis_limit],
    [0, axis_limit],
    color="#B33A3A",
    linestyle="--",
    linewidth=1.8,
    label="Inflow equals preceding-year outflow",
)
for jurisdiction, row in growth_summary.iterrows():
    axis_2.annotate(
        jurisdiction,
        (row["outflow_churn_per_1k"], row["inflow_per_1k"]),
        xytext=(5, 5),
        textcoords="offset points",
        fontsize=9,
    )

axis_2.set(
    title="RN Inflow Intensity vs. Preceding-Year Outflow Churn, 2018–2024",
    xlabel="Average preceding-year outflow (per 1,000 nurses)",
    ylabel="Average current-year inflow (per 1,000 nurses)",
    xlim=(0, axis_limit),
    ylim=(0, axis_limit),
)
axis_2.set_aspect("equal", adjustable="box")
axis_2.legend(loc="upper left")
figure_2.tight_layout()
plt.show()


# %% Figure 3: internationally educated share of annual RN inflow
facet = sns.FacetGrid(
    plot_df,
    col="jurisdiction",
    col_wrap=4,
    col_order=share_change.index.tolist(),
    height=3.3,
    aspect=1.15,
    sharey=True,
)
facet.map_dataframe(
    sns.lineplot,
    x="year",
    y="intl_share_pct",
    marker="o",
    color="#E07A2D",
    linewidth=2,
)


def annotate_endpoints(data: pd.DataFrame, **_: object) -> None:
    """Label 2018 and 2024 values in each facet."""
    axis = plt.gca()
    for year in (2018, 2024):
        endpoint = data.loc[data["year"].eq(year), "intl_share_pct"]
        if not endpoint.empty:
            value = float(endpoint.iloc[0])
            axis.annotate(
                f"{value:.1f}%",
                (year, value),
                xytext=(0, 7),
                textcoords="offset points",
                ha="center",
                fontsize=8,
                fontweight="bold",
            )


facet.map_dataframe(annotate_endpoints)
facet.set_titles("{col_name}", fontweight="bold")
facet.set_axis_labels("Year", "Internationally educated share (%)")
facet.set(xticks=[2018, 2020, 2022, 2024])
facet.figure.subplots_adjust(top=0.88)
facet.figure.suptitle(
    "Internationally Educated Share of RN Inflow, 2018–2024", fontsize=15
)
plt.show()


# %% Findings, limitations, and conclusion
increases = int((share_change["change (percentage points)"] > 0).sum())
decreases = int((share_change["change (percentage points)"] < 0).sum())
largest_increases = share_change.head(3)["change (percentage points)"]
above_break_even = growth_summary.index[
    growth_summary["inflow_per_1k"] > growth_summary["outflow_churn_per_1k"]
].tolist()

print("\nKEY FINDINGS")
print(
    f"1. Average inflow intensity exceeded preceding-year outflow churn in "
    f"{len(above_break_even)} of {len(full_sets)} complete-series jurisdictions."
)
print(
    f"2. The internationally educated share rose in {increases} of "
    f"{len(full_sets)} jurisdictions and fell in {decreases}."
)
print("3. Largest increases in internationally educated share:")
for jurisdiction, change in largest_increases.items():
    print(f"   - {jurisdiction}: {change:+.2f} percentage points")

print("\nLIMITATIONS")
print(
    "The complete-series comparisons exclude Manitoba (missing 2019–2024 data) "
    "and Alberta (missing 2024 data). The analysis is descriptive: it does not "
    "identify causal effects, and outflow should not be interpreted specifically "
    "as retirement. The decomposition discrepancy is retained because the simple "
    "inflow/outflow identity may not capture every source-data adjustment or "
    "workforce movement."
)

print("\nCONCLUSION")
print(
    "Internationally educated nurses represented a growing share of RN inflow "
    "in most complete-series jurisdictions, indicating an increasing role for "
    "international recruitment in workforce growth."
)
