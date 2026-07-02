# Active Context — Marketing Analytics Dashboard

> Last updated: 2026-07-02
> Current Phase: **Phase O — COMPLETED (Frontend: Facebook Ads Detail)**
> Status: **ALL 5 PHASES DONE — Build pass**

---

## Phase A-E — Backend (COMPLETED)

Full backend completed: infra, domain, adapters, ETL, API layer, testing. See `backend/README.md` for details.

---

## Phase K — Init & Design system (COMPLETED)

- K1: `create-next-app` with Next.js 14, TypeScript strict, Tailwind CSS, shadcn/ui, Recharts, TanStack Query, Zustand
- K2: Theme — primary blue `#3B5998`, CSS variables for chart colors (`--chart-action`, `--chart-k1`, `--chart-k2`, `--chart-cost`, `--chart-cpm`), card utilities
- K3: `.env.local.example`, TanStack Query Provider in `components/providers.tsx`, layout integration

## Phase L — Data layer & config (COMPLETED)

- L1: `types/platform-detail.ts` — `PlatformDetailKpis`, `PlatformDetailSeriesPoint`, `PlatformDetailResponse`, `FilterOption`, `TeamInfo`
- L2: `lib/config/filter-fields.ts` — 17 filter field definitions, config-driven (`FilterFieldType`, `FilterFieldConfig`, `FACEBOOK_DETAIL_FILTER_FIELDS`)
- L3: `lib/store/platform-filter-store.ts` — Zustand generic store (`filters: Record<string, unknown>`, `setFilter`, `setSelectedTeamId`, `resetFilters`, `getActiveFilters`)
- L4: `lib/api-client.ts` — `fetchPlatformDetail()`, `fetchFilterOptions()`, centralized URL + API key
- L5: `hooks/usePlatformDetailMetrics.ts` + `hooks/useFilterOptions.ts` — TanStack Query hooks, currently using mock data
- L6: `lib/mock/platform-detail.mock.ts` — Full mock `PlatformDetailResponse` with 10 KPI values, 30-day series, 17 filter options, 12 teams. Marked with `TODO: Thay bằng API thật`

## Phase M — Team Selector & Filter Panel (COMPLETED)

- M1: `TeamSelectorGrid.tsx` — 4-column grid, toggle select/deselect, selected state black bg
- M2: `FilterField/` — 5 control types:
  - `DateRangeField.tsx` — dual date input
  - `SelectField.tsx` — dropdown single-select (static or API options)
  - `MultiSelectField.tsx` — checkbox list dropdown
  - `CheckboxGroupField.tsx` — inline checkbox group (Status: Cut-Off/Normal)
  - `SearchField.tsx` — search input with icon + clear button
- M3: `FilterPanel.tsx` — config-driven render via `renderField()` switch, primary/secondary groups in 6-column grids

## Phase N — KPI & Chart components (COMPLETED)

- N1: `lib/format.ts` — `formatCompactNumber`, `formatCompactCurrency`, `formatPercent`
- N2: `KpiCard.tsx` + `KpiCardGrid.tsx` — 2 rows × 5 columns, config-driven KPI display
- N3: `MetricLineChart.tsx` — 3 lines (Action, K1, K2) single Y-axis with Recharts `<LineChart>`
- N4: `DualAxisLineChart.tsx` — 2 lines (Cost, CPM) dual Y-axis with Recharts `<ComposedChart>` + `yAxisId="left"/"right"`
- N5: `BaseChart.tsx` — wrapper with loading (spinner), error (message), empty ("No data available") states

## Phase O — Page assembly & polish (COMPLETED)

- O1: `app/(dashboard)/[platform]/detail/page.tsx` — layout: header bar (blue primary), TeamSelector + FilterPanel row, KpiCardGrid, 2-column charts
- O2: `app/(dashboard)/[platform]/detail/loading.tsx` — skeleton with pulse animations matching layout
- O3: Build verification — `npx next build` **PASSED** (TypeScript clean, route `/facebook/detail` registered as ƒ dynamic)
- O4: `frontend/README.md` — quick start, project structure, architecture principles, adding filters guide, env vars

---

## Key Files Created (42 files total)

```
frontend/
├── .env.local.example
├── README.md
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── components.json
└── src/
    ├── app/
    │   ├── globals.css
    │   ├── layout.tsx
    │   └── (dashboard)/[platform]/detail/
    │       ├── page.tsx
    │       └── loading.tsx
    ├── components/
    │   ├── providers.tsx
    │   ├── charts/
    │   │   ├── BaseChart.tsx
    │   │   ├── MetricLineChart.tsx
    │   │   ├── DualAxisLineChart.tsx
    │   │   └── chart.types.ts
    │   ├── platform-detail/
    │   │   ├── TeamSelectorGrid.tsx
    │   │   ├── FilterPanel.tsx
    │   │   ├── KpiCard.tsx
    │   │   ├── KpiCardGrid.tsx
    │   │   └── FilterField/
    │   │       ├── DateRangeField.tsx
    │   │       ├── SelectField.tsx
    │   │       ├── MultiSelectField.tsx
    │   │       ├── CheckboxGroupField.tsx
    │   │       └── SearchField.tsx
    │   └── ui/
    ├── hooks/
    │   ├── usePlatformDetailMetrics.ts
    │   └── useFilterOptions.ts
    ├── lib/
    │   ├── api-client.ts
    │   ├── format.ts
    │   ├── config/filter-fields.ts
    │   ├── store/platform-filter-store.ts
    │   └── mock/platform-detail.mock.ts
    └── types/
        └── platform-detail.ts
```

---

## Mock Data Note

All data currently served from `lib/mock/platform-detail.mock.ts`. Search for `TODO: Thay bằng API thật` to find all 4 locations that need switching when backend is ready:

1. `hooks/usePlatformDetailMetrics.ts:14` — uncomment `fetchPlatformDetail()`
2. `hooks/useFilterOptions.ts:10` — uncomment `fetchFilterOptions()`
3. `app/(dashboard)/[platform]/detail/page.tsx:13` — replace `mockTeams` with API
4. Delete `lib/mock/platform-detail.mock.ts` entirely

---

## Next Steps

1. Run `npm run dev` in `frontend/` directory
2. Visit `http://localhost:3000/facebook/detail` — full page renders with mock data
3. Test: click team buttons, change filters, verify KPI + charts update
4. When backend has `/api/v1/platform-detail` endpoint, switch from mock to real API (4 TODO locations above)
5. Extend to `/tiktok/detail` — same components work, just change URL + `FACEBOOK_DETAIL_FILTER_FIELDS` config