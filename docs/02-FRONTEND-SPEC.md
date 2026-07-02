# SPEC: Marketing Analytics Dashboard — Frontend
> Trạng thái: READY FOR PLAN (bỏ qua bước Discuss)
> Đối tượng thực thi: Cline + GSD Core framework
> Phiên bản: 2.0 — cập nhật theo mockup "Facebook Ads Detail" (thay thế bố cục Overview đơn giản ở v1.0)
> Phụ thuộc: `docs/01-SPEC.md` (Backend & Database) — **có điểm cần mở rộng, xem mục 0**

---

## 0. GHI CHÚ QUAN TRỌNG — ĐIỂM CẦN ĐỐI CHIẾU VỚI BACKEND TRƯỚC KHI CODE

Mockup yêu cầu nhiều dimension và metric **không có sẵn** trong `docs/01-SPEC.md` bản gốc (vốn chỉ có `spend/impressions/clicks/conversions` và dimension `campaign/ad_set/ad`). Cụ thể:

**Dimension mới cần có** (hiện chưa có cột tương ứng trong `dim_campaign`/`dim_ad_set`/`dim_ad`):
`Team`, `Team Type`, `Status (Cut-Off/Normal)`, `Objective`, `Keymess`, `Content Group`, `Content code`, `Getback`, `Product`, `Industry`, `Sale Team`, `Month by campaign`.

**Metric custom cần có** (không phải metric chuẩn của Facebook Ads API):
`Action`, `K1`, `K2`, `Doanh thu kỳ vọng`, `CPM`, `CPA`, `CPK1`, `CPK2`, `% Chi phí`.

Đây rõ ràng là dữ liệu **đã qua xử lý nghiệp vụ nội bộ** (không phải raw response từ Facebook Marketing API) — nhiều khả năng `K1`, `K2`, `Action`, `Getback` đến từ 1 nguồn khác (CRM, Google Sheet tracking, hệ thống Sale) được join với chi phí quảng cáo theo `content_code`/`campaign`. Frontend không tự bịa được các số này — chúng phải do backend tính và trả về.

**Giả định tao dùng để viết spec này** (mày cần xác nhận hoặc chỉnh lại):
- `Action`, `K1`, `K2` là 3 mốc chuyển đổi (conversion funnel) do nghiệp vụ tự định nghĩa, khác `conversions` chuẩn — lưu trong `extra_metrics JSONB` của `fact_ad_metrics` (đúng theo thiết kế hybrid ở `01-SPEC.md` mục 4.1: metric phổ biến là cột cứng, metric đặc thù nằm JSONB).
- `CPM = Cost / Impressions`, `CPA = Cost / Action`, `CPK1 = Cost / K1`, `CPK2 = Cost / K2`, `% Chi phí = Cost / Doanh thu kỳ vọng` — đều là tỷ lệ dẫn xuất, **backend tính sẵn**, không tính ở frontend (giữ đúng nguyên tắc mục 1.3.5 bên dưới).
- `Doanh thu kỳ vọng` (expected revenue) là số nhập tay hoặc tính từ hệ thống khác — coi như 1 metric có sẵn trong `extra_metrics`, không phải frontend tự nhân giá trị đơn hàng.
- Các dimension mới (Team, Product, Industry, Content Group, Content code, Getback, Sale Team...) coi như thuộc tính mở rộng của `dim_campaign`/`dim_ad_set`, lưu trong cột `targeting_meta JSONB` đã có sẵn ở `dim_ad_set`, hoặc cần thêm bảng `dim_content_code` riêng nếu Content code là 1 thực thể độc lập được quản lý riêng (có vẻ đúng — vì mockup có ô "Select All Content code" dạng search riêng biệt).

> **Việc cần làm trước khi Cline code phần này**: bổ sung 1 mục vào `docs/01-SPEC.md` (hoặc file phụ lục riêng, VD `docs/01a-CUSTOM-METRICS-ADDENDUM.md`) mô tả rõ nguồn dữ liệu và công thức của `Action/K1/K2/Getback/Doanh thu kỳ vọng`, và bổ sung dimension mới vào DDL (`database/`). Spec frontend này viết trên giả định trên — nếu công thức thực tế khác, chỉ cần sửa lại tầng tính toán ở backend, **không ảnh hưởng cấu trúc component frontend** (vì frontend chỉ hiển thị số đã tính sẵn).

---

## 1. TỔNG QUAN & MỤC TIÊU

### 1.1 Bài toán
Xây dựng trang **chi tiết báo cáo theo từng nền tảng** (VD: "Facebook Ads Detail"), tái sử dụng được cho TikTok/Google sau này bằng cách đổi tham số `platform`. Trang hiển thị bộ filter phong phú, dàn KPI card 2 hàng, và 2 biểu đồ xu hướng theo thời gian.

### 1.2 Phạm vi (Scope) đợt 1
- **Trong scope:** Trang Platform Detail cho Facebook Ads theo đúng bố cục mockup: Team selector grid, bộ filter đầy đủ (Date, Team Type, KPI/Extra, Status, Objective, Keymess, Ad ID, Campaign ID, Campaign Name, Content Group, Content code search + dropdown, Getback, Product, Industry, Sale Team, Month by campaign), 10 KPI card (2 hàng x 5 cột), 2 chart xu hướng (multi-line và dual-axis).
- **Ngoài scope (đợt 1):** Trang Overview cross-platform tổng hợp (giữ lại thiết kế ở v1.0 làm tham khảo, triển khai sau khi trang Detail ổn định), export báo cáo, real-time update.
- Component được thiết kế **tổng quát theo platform param** ngay từ đầu — để khi làm TikTok/Google Detail chỉ cần đổi `platform` prop, không viết lại trang.

### 1.3 Nguyên tắc kiến trúc bắt buộc
1. **Tách biệt hoàn toàn Data layer khỏi UI layer**: mọi gọi API đi qua custom hooks (`hooks/`), component KHÔNG tự fetch trực tiếp.
2. **Component chart tái sử dụng**: `BaseChart` wrapper dùng chung cho `MetricLineChart` (multi-line) và `DualAxisLineChart` (2 trục Y khác đơn vị, dùng cho "Cost and CPM by Period").
3. **Filter state tập trung 1 nơi**: toàn bộ ~17 filter trong mockup đọc/ghi vào 1 store duy nhất theo `platform` hiện tại — không state rải rác từng component.
4. **Filter panel tách khỏi danh sách field**: cấu hình field nào hiển thị, thứ tự, loại control (dropdown/multi-select/date range/checkbox/search) khai báo dưới dạng config array — không hardcode JSX lặp lại cho từng field, để dễ thêm/bớt filter mà không sửa logic layout.
5. **Không tính toán nghiệp vụ ở frontend**: `Cost`, `Action`, `K1`, `K2`, `Doanh thu kỳ vọng`, `CPM`, `CPA`, `CPK1`, `CPK2`, `% Chi phí` đều do backend trả sẵn — frontend chỉ format hiển thị (đơn vị M/K, %, VNĐ).

---

## 2. YÊU CẦU CHỨC NĂNG (FUNCTIONAL REQUIREMENTS)

### 2.1 Team Selector (góc trái trên)
| ID | Yêu cầu | Ưu tiên |
|---|---|---|
| FR-01 | Hiển thị lưới nút số (Team ID) dạng ma trận 4 cột — dữ liệu từ danh sách team thật, không hardcode số lượng | Must |
| FR-02 | Cho phép chọn 1 team (single-select, click đổi màu nền đen như mockup) hoặc "tất cả" (không chọn ô nào = xem tất cả) | Must |
| FR-03 | Chọn Team → toàn bộ filter, KPI card, chart bên phải tự cập nhật theo team đó | Must |

### 2.2 Filter Panel (khu vực trên cùng, bên phải Team Selector)
| ID | Yêu cầu | Ưu tiên |
|---|---|---|
| FR-04 | Date Range: 2 ô nhập ngày (from/to), không cần preset nhanh ở bản mockup này (khác v1.0) | Must |
| FR-05 | Team Type: dropdown single-select | Must |
| FR-06 | KPI/Extra: dropdown single-select | Should |
| FR-07 | Status: checkbox group (Cut-Off, Normal) — multi-select qua checkbox, không phải dropdown | Must |
| FR-08 | Objective: dropdown single-select | Should |
| FR-09 | Keymess: dropdown single-select | Should |
| FR-10 | Ad ID: dropdown (multi-select ẩn dưới "All") | Should |
| FR-11 | Campaign ID: dropdown (multi-select ẩn dưới "All") | Must |
| FR-12 | Campaign Name: dropdown (multi-select ẩn dưới "All") | Must |
| FR-13 | Content Group: dropdown single/multi-select | Should |
| FR-14 | Select All Content code: ô search riêng biệt (input text + icon kính lúp + icon xoá), lọc nhanh trong danh sách content_code lớn | Must |
| FR-15 | content_code: dropdown, kết quả bị lọc bởi ô search ở FR-14 | Must |
| FR-16 | Getback: dropdown single-select | Should |
| FR-17 | Product: dropdown single-select | Should |
| FR-18 | Industry: dropdown single-select | Should |
| FR-19 | Sale Team: dropdown single-select | Should |
| FR-20 | Month by campaign: dropdown single-select | Should |
| FR-21 | Mọi filter dropdown mặc định hiển thị "All" khi chưa chọn gì | Must |

### 2.3 KPI Cards (2 hàng x 5 cột)
| ID | Yêu cầu | Ưu tiên |
|---|---|---|
| FR-22 | Hàng 1: Cost, Action, K1, K2, Doanh thu kỳ vọng — số lớn định dạng rút gọn (98.7M, 944, 670, 339, 219.14M) | Must |
| FR-23 | Hàng 2: CPM, CPA, CPK1, CPK2, % Chi phí — CPM/CPA/CPK1/CPK2 định dạng rút gọn (67K, 105K...), % Chi phí định dạng phần trăm 2 chữ số thập phân | Must |
| FR-24 | Card gồm: số lớn ở trên, label mô tả ở dưới, canh giữa — đúng bố cục mockup, không thêm icon/màu trạng thái (mockup không có so sánh kỳ trước ở bản này) | Must |
| FR-25 | Card responsive: 5 card/hàng trên desktop, tự động wrap xuống hàng khi màn hình hẹp | Should |

### 2.4 Charts
| ID | Yêu cầu | Ưu tiên |
|---|---|---|
| FR-26 | Chart 1 "Action, K1 and K2 by Period": line chart 3 đường (Action, K1, K2), cùng 1 trục Y, trục X là Date (theo ngày trong khoảng đã lọc) | Must |
| FR-27 | Chart 2 "Cost and CPM by Period": line chart 2 đường nhưng **2 trục Y khác nhau** — trục trái cho Cost (đơn vị M), trục phải cho CPM (đơn vị K) — đúng dual-axis như mockup | Must |
| FR-28 | Legend hiển thị trên đầu mỗi chart, click vào legend item để ẩn/hiện đường tương ứng | Should |
| FR-29 | Tooltip hover hiển thị giá trị chính xác tại điểm dữ liệu | Must |
| FR-30 | Loading/Error/Empty state nhất quán qua `BaseChart` (giữ nguyên nguyên tắc v1.0) | Must |

---

## 3. YÊU CẦU PHI CHỨC NĂNG (NON-FUNCTIONAL REQUIREMENTS)

| ID | Yêu cầu |
|---|---|
| NFR-01 | Next.js 14+ (App Router), TypeScript strict mode |
| NFR-02 | Styling: Tailwind CSS + shadcn/ui — theme màu chính lấy theo tông xanh dương của mockup (header bar `#3B5998`-like blue) |
| NFR-03 | Charting library: Recharts, dùng `<ComposedChart>` với `yAxisId="left"`/`yAxisId="right"` cho dual-axis chart (giữ quyết định Recharts đã chốt ở v1.0, không đổi) |
| NFR-04 | Data fetching & cache: TanStack Query, KHÔNG dùng `useEffect` + `fetch` thủ công |
| NFR-05 | Toàn bộ endpoint URL, API key đọc từ `.env.local`, không hardcode |
| NFR-06 | Type-safe: type response khớp chính xác schema backend (bao gồm cả field mở rộng ở mục 0) |
| NFR-07 | Danh sách filter dài (17 field) phải khai báo dạng config-driven (mảng object `{key, label, type, optionsSource}`), KHÔNG viết tay từng JSX lặp lại — để thêm/bớt filter chỉ sửa config, không sửa component logic |

---

## 4. KIẾN TRÚC & LUỒNG DỮ LIỆU

### 4.1 Sơ đồ luồng

```
[Team Selector] ──┐
                   │
[Filter Panel] ────┤──► [Filter Store (Zustand), scoped theo platform] ───┐
(17 field)         │                                                     │
                   │                                                     ▼
                   │                                          ┌────────────────────┐
                   │                                          │ hooks/usePlatform-  │
                   │                                          │ DetailMetrics(platform)│
                   │                                          └────────────────────┘
                                                                          │  queryKey = ['platform-detail', platform, filters]
                                                                          ▼
                                                               ┌────────────────────┐
                                                               │  lib/api-client.ts  │
                                                               └────────────────────┘
                                                                          │  GET /api/v1/platform-detail
                                                                          ▼
                                                            Backend FastAPI (cần bổ sung endpoint mới — mục 5)
                                                                          │
                                                                          ▼
                                                    { kpis: {...}, series: [...], filterOptions: {...} }
                                            ┌───────────────────┬────────────────────────┐
                                            ▼                   ▼                        ▼
                                     KpiCardGrid          MetricLineChart          DualAxisLineChart
                                  (Cost/Action/K1/K2/     (Action, K1, K2           (Cost vs CPM
                                   DoanhThu/CPM/CPA/       by Period)                by Period)
                                   CPK1/CPK2/%ChiPhi)
```

### 4.2 Filter state — config-driven (khác v1.0, vì số lượng filter lớn hơn nhiều)

```typescript
// lib/config/filter-fields.ts
export type FilterFieldType = 'dateRange' | 'select' | 'multiSelect' | 'checkboxGroup' | 'search';

export interface FilterFieldConfig {
  key: string;                 // 'teamType' | 'status' | 'campaignId' | ...
  label: string;
  type: FilterFieldType;
  optionsSource?: 'static' | 'api';   // 'static' cho Status (Cut-Off/Normal), 'api' cho Campaign/ContentCode...
  apiEndpoint?: string;               // nếu optionsSource = 'api'
  group: 'primary' | 'secondary';     // primary = hàng filter chính, secondary = filter phụ
}

export const FACEBOOK_DETAIL_FILTER_FIELDS: FilterFieldConfig[] = [
  { key: 'dateRange', label: 'Date', type: 'dateRange', group: 'primary' },
  { key: 'teamType', label: 'Team Type', type: 'select', optionsSource: 'api', group: 'primary' },
  { key: 'kpiExtra', label: 'KPI/ Extra', type: 'select', optionsSource: 'static', group: 'primary' },
  { key: 'status', label: 'Status', type: 'checkboxGroup', optionsSource: 'static', group: 'primary' },
  { key: 'objective', label: 'Objective', type: 'select', optionsSource: 'api', group: 'primary' },
  { key: 'keymess', label: 'Keymess', type: 'select', optionsSource: 'api', group: 'primary' },
  { key: 'adId', label: 'Ad ID', type: 'multiSelect', optionsSource: 'api', apiEndpoint: '/api/v1/facebook/ads', group: 'secondary' },
  { key: 'campaignId', label: 'Campaign ID', type: 'multiSelect', optionsSource: 'api', apiEndpoint: '/api/v1/campaigns', group: 'secondary' },
  { key: 'campaignName', label: 'Campaign Name', type: 'multiSelect', optionsSource: 'api', apiEndpoint: '/api/v1/campaigns', group: 'secondary' },
  { key: 'contentGroup', label: 'Content Group', type: 'select', optionsSource: 'api', group: 'secondary' },
  { key: 'contentCodeSearch', label: 'Select All Content code', type: 'search', group: 'secondary' },
  { key: 'contentCode', label: 'content_code', type: 'select', optionsSource: 'api', group: 'secondary' },
  { key: 'getback', label: 'Getback', type: 'select', optionsSource: 'api', group: 'secondary' },
  { key: 'product', label: 'Product', type: 'select', optionsSource: 'api', group: 'secondary' },
  { key: 'industry', label: 'Industry', type: 'select', optionsSource: 'api', group: 'secondary' },
  { key: 'saleTeam', label: 'Sale Team', type: 'select', optionsSource: 'api', group: 'secondary' },
  { key: 'monthByCampaign', label: 'Month by campaign', type: 'select', optionsSource: 'api', group: 'secondary' },
];
```

`FilterPanel.tsx` chỉ đọc mảng config này, `map()` ra control tương ứng theo `type` — thêm filter mới = thêm 1 object vào mảng, không sửa component.

### 4.3 Type-safe API Client (bổ sung so với v1.0)

```typescript
// types/platform-detail.ts
export interface PlatformDetailKpis {
  cost: number;
  action: number;
  k1: number;
  k2: number;
  expected_revenue: number;   // "Doanh thu kỳ vọng"
  cpm: number;
  cpa: number;
  cpk1: number;
  cpk2: number;
  cost_ratio_pct: number;     // "% Chi phí"
}

export interface PlatformDetailSeriesPoint {
  date: string;
  action: number;
  k1: number;
  k2: number;
  cost: number;
  cpm: number;
}

export interface PlatformDetailResponse {
  kpis: PlatformDetailKpis;
  series: PlatformDetailSeriesPoint[];
  filterOptions: Record<string, { value: string; label: string }[]>;
}
```

---

## 5. YÊU CẦU BỔ SUNG PHÍA BACKEND (để mày đối chiếu, không thuộc phạm vi frontend nhưng bắt buộc phải có trước khi frontend chạy được thật)

- Endpoint mới: `GET /api/v1/platform-detail?platform=FACEBOOK&team_id=...&date_from=...&date_to=...&status[]=...&content_code[]=...&...`
  Trả về đúng shape `PlatformDetailResponse` ở mục 4.3.
- Endpoint filter options: `GET /api/v1/platform-detail/filter-options?platform=FACEBOOK` — trả về danh sách giá trị hợp lệ cho từng dropdown (Team Type, Objective, Keymess, Content Group, content_code, Getback, Product, Industry, Sale Team, Month by campaign) để tránh hardcode ở frontend.
- Bảng `dim_campaign`/`dim_ad_set` cần bổ sung cột hoặc mở rộng `targeting_meta JSONB` để lưu: `team_id`, `team_type`, `objective`, `keymess`, `content_group`, `content_code`, `getback`, `product`, `industry`, `sale_team`.
- `fact_ad_metrics.extra_metrics` cần có key: `action`, `k1`, `k2`, `expected_revenue`, và các tỷ lệ `cpm/cpa/cpk1/cpk2/cost_ratio_pct` nên **tính sẵn ở backend** (SQL hoặc application layer), không để frontend tự chia.

> Nếu backend chưa có endpoint này, frontend Phase K (mục 6) vẫn build được UI hoàn chỉnh bằng mock data đúng shape `PlatformDetailResponse`, đánh dấu rõ chỗ mock để thay sau.

---

## 6. CẤU TRÚC THƯ MỤC BẮT BUỘC

```
frontend/
├── app/
│   ├── (dashboard)/
│   │   ├── [platform]/
│   │   │   └── detail/
│   │   │       └── page.tsx            # trang chi tiết, platform lấy từ URL param
│   │   └── page.tsx                    # (giữ lại, đợt sau) trang Overview cross-platform
│   ├── layout.tsx
│   └── globals.css
├── components/
│   ├── charts/
│   │   ├── BaseChart.tsx
│   │   ├── MetricLineChart.tsx         # multi-line, 1 trục Y (Action/K1/K2)
│   │   ├── DualAxisLineChart.tsx       # 2 trục Y (Cost vs CPM)
│   │   └── chart.types.ts
│   ├── platform-detail/
│   │   ├── TeamSelectorGrid.tsx        # lưới nút Team
│   │   ├── FilterPanel.tsx             # render config-driven (mục 4.2)
│   │   ├── FilterField/                # từng loại control
│   │   │   ├── DateRangeField.tsx
│   │   │   ├── SelectField.tsx
│   │   │   ├── MultiSelectField.tsx
│   │   │   ├── CheckboxGroupField.tsx
│   │   │   └── SearchField.tsx
│   │   ├── KpiCard.tsx
│   │   └── KpiCardGrid.tsx             # 2 hàng x 5 cột
│   └── ui/
├── hooks/
│   ├── usePlatformDetailMetrics.ts     # nhận platform + filters
│   └── useFilterOptions.ts             # gọi /filter-options theo platform
├── lib/
│   ├── api-client.ts
│   ├── config/
│   │   └── filter-fields.ts            # mục 4.2
│   ├── store/
│   │   └── platform-filter-store.ts    # Zustand, scoped theo platform
│   ├── format.ts
│   └── date-utils.ts
├── types/
│   ├── platform-detail.ts              # mục 4.3
│   └── metrics.ts                      # giữ lại cho trang Overview đợt sau
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── .env.local.example
└── README.md
```

---

## 7. CHI TIẾT COMPONENT CHÍNH

### 7.1 `TeamSelectorGrid.tsx`
```tsx
interface TeamSelectorGridProps {
  teams: { id: number }[];
  selectedTeamId: number | null;
  onSelect: (teamId: number | null) => void;
  columns?: number;   // mặc định 4 theo mockup
}
```
Click vào ô đang chọn lần nữa → bỏ chọn (trở về "tất cả"), đúng hành vi toggle như filter thông thường, không phải radio bắt buộc phải chọn 1.

### 7.2 `FilterPanel.tsx` — render config-driven
```tsx
export function FilterPanel({ fields }: { fields: FilterFieldConfig[] }) {
  const primary = fields.filter(f => f.group === 'primary');
  const secondary = fields.filter(f => f.group === 'secondary');
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-6 gap-4">{primary.map(renderField)}</div>
      <div className="grid grid-cols-6 gap-4">{secondary.map(renderField)}</div>
    </div>
  );
}

function renderField(field: FilterFieldConfig) {
  switch (field.type) {
    case 'dateRange': return <DateRangeField key={field.key} config={field} />;
    case 'select': return <SelectField key={field.key} config={field} />;
    case 'multiSelect': return <MultiSelectField key={field.key} config={field} />;
    case 'checkboxGroup': return <CheckboxGroupField key={field.key} config={field} />;
    case 'search': return <SearchField key={field.key} config={field} />;
  }
}
```
Mỗi `FilterField/*` tự đọc/ghi giá trị của đúng `field.key` vào `platform-filter-store.ts` — không cần `FilterPanel` biết logic bên trong từng loại control.

### 7.3 `KpiCard.tsx` / `KpiCardGrid.tsx`
```tsx
interface KpiCardConfig {
  key: keyof PlatformDetailKpis;
  label: string;
  format: 'compactNumber' | 'compactCurrency' | 'percent';
}

const ROW_1: KpiCardConfig[] = [
  { key: 'cost', label: 'Cost', format: 'compactCurrency' },
  { key: 'action', label: 'Action', format: 'compactNumber' },
  { key: 'k1', label: 'K1', format: 'compactNumber' },
  { key: 'k2', label: 'K2', format: 'compactNumber' },
  { key: 'expected_revenue', label: 'Doanh thu kỳ vọng', format: 'compactCurrency' },
];
const ROW_2: KpiCardConfig[] = [
  { key: 'cpm', label: 'CPM', format: 'compactCurrency' },
  { key: 'cpa', label: 'CPA', format: 'compactCurrency' },
  { key: 'cpk1', label: 'CPK1', format: 'compactCurrency' },
  { key: 'cpk2', label: 'CPK2', format: 'compactCurrency' },
  { key: 'cost_ratio_pct', label: '% Chi phí', format: 'percent' },
];
```
`compactNumber`/`compactCurrency` dùng chung hàm `lib/format.ts` (`98700000 → "98.7M"`) — 1 hàm duy nhất, KPI card chỉ truyền `format` type, không tự viết logic rút gọn số riêng lẻ từng nơi.

### 7.4 `DualAxisLineChart.tsx`
```tsx
<ComposedChart data={series}>
  <XAxis dataKey="date" />
  <YAxis yAxisId="left" label={{ value: 'Cost', angle: -90 }} />
  <YAxis yAxisId="right" orientation="right" label={{ value: 'CPM', angle: 90 }} />
  <Line yAxisId="left" dataKey="cost" stroke="var(--chart-cost)" />
  <Line yAxisId="right" dataKey="cpm" stroke="var(--chart-cpm)" />
  <Tooltip />
  <Legend />
</ComposedChart>
```
Bọc trong `BaseChart` như mọi chart khác — giữ nhất quán loading/error/empty state.

---

## 8. ENVIRONMENT VARIABLES

Không đổi so với v1.0 — xem `frontend/.env.local.example`:
```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_API_KEY=change-me-to-a-random-secret
```

---

## 9. TASK BREAKDOWN CHO GSD PLAN PHASE

> Thay thế Phase F-J cũ ở v1.0 (đã lỗi thời so với mockup này). Đặt tên lại từ Phase K để không đụng số đã dùng trong `.gsd/memory-bank/progress.md` nếu Phase F-J đã bắt đầu chạy — nếu chưa chạy gì, có thể dùng lại F-J bình thường.

### Phase K — Khởi tạo & Design system
- [ ] K1. `create-next-app` + Tailwind + shadcn/ui + recharts + TanStack Query + zustand (giữ nguyên như v1.0).
- [ ] K2. Setup theme màu theo mockup (header xanh dương, card viền xám nhạt bo góc).
- [ ] K3. `.env.local.example`, TanStack Query Provider.

### Phase L — Data layer & config
- [ ] L1. `types/platform-detail.ts` (mục 4.3).
- [ ] L2. `lib/config/filter-fields.ts` (mục 4.2) — khai báo đủ 17 field theo mockup.
- [ ] L3. `lib/store/platform-filter-store.ts` — Zustand store generic theo `Record<string, any>` khớp với `filter-fields.ts` keys, không hardcode từng field riêng.
- [ ] L4. `lib/api-client.ts`: `fetchPlatformDetail(platform, filters)`, `fetchFilterOptions(platform)`.
- [ ] L5. `hooks/usePlatformDetailMetrics.ts`, `hooks/useFilterOptions.ts`.
- [ ] L6. Nếu backend chưa có endpoint mục 5 → tạo `lib/mock/platform-detail.mock.ts` khớp đúng `PlatformDetailResponse`, đánh dấu rõ `// TODO: thay bằng API thật khi backend sẵn sàng`.

### Phase M — Component: Team Selector & Filter Panel
- [ ] M1. `components/platform-detail/TeamSelectorGrid.tsx`.
- [ ] M2. `components/platform-detail/FilterField/*` (5 loại control theo mục 4.2).
- [ ] M3. `components/platform-detail/FilterPanel.tsx` — render config-driven.
- [ ] M4. Test: đổi bất kỳ filter nào → store cập nhật đúng key, không ảnh hưởng field khác.

### Phase N — Component: KPI & Chart
- [ ] N1. `lib/format.ts`: `formatCompactNumber`, `formatCompactCurrency`, `formatPercent`.
- [ ] N2. `components/platform-detail/KpiCard.tsx`, `KpiCardGrid.tsx` (mục 7.3).
- [ ] N3. `components/charts/MetricLineChart.tsx` cho "Action, K1 and K2 by Period".
- [ ] N4. `components/charts/DualAxisLineChart.tsx` cho "Cost and CPM by Period" (mục 7.4).

### Phase O — Ráp trang & hoàn thiện
- [ ] O1. `app/(dashboard)/[platform]/detail/page.tsx` — ráp TeamSelector + FilterPanel + KpiCardGrid + 2 chart đúng layout mockup (Team bên trái, Filter bên phải cùng hàng trên; KPI 2 hàng; chart 2 cột dưới cùng).
- [ ] O2. `app/(dashboard)/[platform]/detail/loading.tsx`.
- [ ] O3. Test route `/facebook/detail` hiển thị đúng tiêu đề "FACEBOOK ADS DETAIL" (tên platform lấy từ URL param, không hardcode).
- [ ] O4. Cập nhật `frontend/README.md`.

---

## 10. TIÊU CHÍ NGHIỆM THU (ACCEPTANCE CRITERIA)

1. Trang `/facebook/detail` hiển thị đúng bố cục: Team grid trái trên, 17 filter phải trên, 10 KPI card giữa, 2 chart dưới cùng — khớp thứ tự và nhóm như mockup.
2. Chọn 1 Team trong grid → toàn bộ KPI card và chart cập nhật theo team đó; bỏ chọn → trở về xem tất cả.
3. Đổi Date Range hoặc bất kỳ filter nào trong 17 field → gọi lại API đúng 1 lần (không gọi thừa do re-render), KPI + chart cập nhật.
4. Ô "Select All Content code" search đúng lọc được danh sách trong dropdown `content_code` bên cạnh.
5. Chart "Cost and CPM by Period" hiển thị đúng 2 trục Y riêng biệt, không bị co giãn sai tỷ lệ khi giá trị Cost (đơn vị triệu) và CPM (đơn vị nghìn) chênh lệch lớn.
6. Thêm 1 filter mới (giả lập) chỉ cần thêm 1 object vào `filter-fields.ts` — không sửa `FilterPanel.tsx`.
7. Khi đổi URL param platform (giả lập `/tiktok/detail`), toàn bộ component tái sử dụng được, chỉ tiêu đề/icon header đổi theo platform — không phải viết trang riêng.
