"use client";

/**
 * The filter panel of the Leads search screen (task M3-A3).
 *
 * Needed so BD can build a `FilterSet` with the control that fits each filter: collapsible
 * checkbox lists for values read from the data, term boxes for job title and company name, two
 * number boxes for revenue, a three-way choice for Salesforce use and for each status flag, and
 * the two view toggles (D-024, D-025, D-106). Changes only edit a draft; "Apply filters" hands it
 * to the screen, so a click on a checkbox does not fire a search. The server still validates
 * everything.
 */
import { useState } from "react";

import CheckboxGroup from "@/components/search/CheckboxGroup";
import styles from "@/components/search/search.module.css";
import TermInput from "@/components/search/TermInput";
import type { FilterOptionsResponse, LeadStatusFlagType, SizeBand } from "@/lib/api/types.gen";
import type { FilterSet } from "@/lib/search/filters";
import {
  FLAG_LABELS,
  SIZE_BAND_LABELS,
  addTerm,
  flagMode,
  listValues,
  parseRevenue,
  revenueError,
  setEligibleOnly,
  setFlagMode,
  setShowOptedOut,
  toggleListValue,
  toggleSizeBand,
  type FlagMode,
  type ListField,
} from "@/lib/search/filters";

const FLAG_MODES: ReadonlyArray<{ value: FlagMode; label: string }> = [
  { value: "any", label: "Any" },
  { value: "include", label: "Must have" },
  { value: "exclude", label: "Must not have" },
];

type OptionsKey = "industries" | "countries" | "states" | "cities" | "technologies" | "funding_stages";

/** Value-list filters in display order: the filter field, its heading and its options list. */
const CHECKBOX_FILTERS: ReadonlyArray<{ field: ListField; title: string; optionsKey: OptionsKey }> = [
  { field: "industries", title: "Industry", optionsKey: "industries" },
  { field: "countries", title: "Country", optionsKey: "countries" },
  { field: "states", title: "State", optionsKey: "states" },
  { field: "cities", title: "City", optionsKey: "cities" },
  { field: "technologies", title: "Technology", optionsKey: "technologies" },
  { field: "funding_stages", title: "Funding stage", optionsKey: "funding_stages" },
];

function asOptions(values: readonly string[]) {
  return values.map((value) => ({ value, label: value }));
}

/** Renders every filter control and the Apply and Clear buttons. */
export default function FilterPanel({
  draft,
  options,
  onChange,
  onApply,
  onClear,
}: Readonly<{
  draft: FilterSet;
  options: FilterOptionsResponse | null;
  onChange: (next: FilterSet) => void;
  onApply: (filters: FilterSet) => void;
  onClear: () => void;
}>) {
  // Revenue is typed text until Apply, so half-typed numbers such as "1." never reach the filter.
  const [revenueMin, setRevenueMin] = useState(draft.revenue_min?.toString() ?? "");
  const [revenueMax, setRevenueMax] = useState(draft.revenue_max?.toString() ?? "");
  const [error, setError] = useState<string | null>(null);

  function apply() {
    const problem = revenueError(revenueMin, revenueMax);
    setError(problem);
    if (problem) return;
    const min = parseRevenue(revenueMin);
    const max = parseRevenue(revenueMax);
    onApply({
      ...draft,
      revenue_min: min === "invalid" ? null : min,
      revenue_max: max === "invalid" ? null : max,
    });
  }

  const truncated = options?.truncated ?? [];
  const flagOptions: readonly LeadStatusFlagType[] = options?.flags ?? [];

  return (
    <form
      className={styles.panel}
      aria-label="Search filters"
      onSubmit={(e) => {
        e.preventDefault();
        apply();
      }}
    >
      <div className={styles.panelHead}>Filters</div>
      <div className={styles.panelBody}>
        {CHECKBOX_FILTERS.map(({ field, title, optionsKey }) => (
          <CheckboxGroup
            key={field}
            title={title}
            options={asOptions(options?.[optionsKey] ?? [])}
            selected={listValues(draft, field)}
            onToggle={(value) => onChange(toggleListValue(draft, field, value))}
            truncated={truncated.includes(optionsKey)}
            defaultOpen={field === "industries"}
          />
        ))}
        <CheckboxGroup
          title="Company size"
          options={(options?.size_bands ?? []).map((band) => ({
            value: band,
            label: SIZE_BAND_LABELS[band],
          }))}
          selected={draft.size_bands ?? []}
          onToggle={(value) => onChange(toggleSizeBand(draft, value as SizeBand))}
          defaultOpen
        />

        <TermInput
          label="Job title"
          terms={listValues(draft, "titles")}
          onAdd={(term) => onChange(addTerm(draft, "titles", term))}
          onRemove={(term) => onChange(toggleListValue(draft, "titles", term))}
        />
        <TermInput
          label="Company name"
          terms={listValues(draft, "company_names")}
          onAdd={(term) => onChange(addTerm(draft, "company_names", term))}
          onRemove={(term) => onChange(toggleListValue(draft, "company_names", term))}
        />

        <section className={styles.section}>
          <div className={styles.sectionBody} style={{ paddingTop: 12 }}>
            <div className={styles.fieldRow}>
              <label className={styles.fieldLabel}>
                <span>Minimum revenue</span>
                <input
                  type="text"
                  inputMode="decimal"
                  className={styles.input}
                  value={revenueMin}
                  onChange={(e) => setRevenueMin(e.target.value)}
                />
              </label>
              <label className={styles.fieldLabel}>
                <span>Maximum revenue</span>
                <input
                  type="text"
                  inputMode="decimal"
                  className={styles.input}
                  value={revenueMax}
                  onChange={(e) => setRevenueMax(e.target.value)}
                />
              </label>
            </div>
            <label className={styles.fieldLabel}>
              <span>Uses Salesforce</span>
              <select
                className={styles.select}
                value={
                  draft.uses_salesforce === null || draft.uses_salesforce === undefined
                    ? "any"
                    : String(draft.uses_salesforce)
                }
                onChange={(e) =>
                  onChange({
                    ...draft,
                    uses_salesforce: e.target.value === "any" ? null : e.target.value === "true",
                  })
                }
              >
                <option value="any">Any</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </label>
          </div>
        </section>

        {flagOptions.length > 0 && (
          <section className={styles.section}>
            <div className={styles.sectionBody} style={{ paddingTop: 12 }}>
              {flagOptions.map((flag) => (
                <label className={styles.fieldLabel} key={flag}>
                  <span>{FLAG_LABELS[flag]}</span>
                  <select
                    className={styles.select}
                    value={flagMode(draft, flag)}
                    onChange={(e) => onChange(setFlagMode(draft, flag, e.target.value as FlagMode))}
                  >
                    {FLAG_MODES.map(({ value, label }) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          </section>
        )}

        <section className={styles.section}>
          <div className={styles.sectionBody} style={{ paddingTop: 12 }}>
            <label className={styles.option}>
              <input
                type="checkbox"
                checked={draft.eligible_only ?? false}
                onChange={(e) => onChange(setEligibleOnly(draft, e.target.checked))}
              />
              <span>Eligible only</span>
            </label>
            <label className={styles.option}>
              <input
                type="checkbox"
                checked={draft.show_opted_out ?? false}
                onChange={(e) => onChange(setShowOptedOut(draft, e.target.checked))}
              />
              <span>Show opted-out</span>
            </label>
          </div>
        </section>
      </div>

      {error && (
        <p className={styles.error} role="alert" style={{ margin: "0 14px 12px" }}>
          {error}
        </p>
      )}
      <div className={styles.panelFooter}>
        <button className={styles.primary} type="submit">
          Apply filters
        </button>
        <button className={styles.secondary} type="button" onClick={onClear}>
          Clear all
        </button>
      </div>
    </form>
  );
}
