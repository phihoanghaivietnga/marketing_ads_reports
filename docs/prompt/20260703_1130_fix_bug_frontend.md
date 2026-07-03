Dashboard Facebook Ads Detail hiện có bug: đổi filter (Date, Team, Status, Campaign...) nhưng KHÔNG thấy KPI card / chart cập nhật số liệu. Không có nút để chủ động trigger việc load báo cáo. Sửa theo đúng các bước sau, làm tuần tự, không nhảy cóc.

## Bước 1 — Chẩn đoán trước khi sửa (bắt buộc, báo cáo lại cho tao)
Kiểm tra và trả lời rõ 3 câu hỏi sau trước khi đổi bất kỳ dòng code nào:
1. `app/(dashboard)/[platform]/detail/page.tsx` và các component KPI/Chart đang lấy data từ đâu — từ `hooks/usePlatformDetailMetrics()` (đúng thiết kế) hay đang có data hardcode/mock gắn cứng trong component (sai)?
2. `hooks/usePlatformDetailMetrics.ts` — `queryKey` của `useQuery` có bao gồm đầy đủ object filters (đọc từ `platform-filter-store.ts`) không? 
Nếu `queryKey` là hằng số cố định (VD chỉ `['platform-detail']` không kèm filters), đó là nguyên nhân chính khiến TanStack Query coi mọi lần đổi filter là "cùng 1 query" nên không refetch.
3. Các `FilterField/*` component (DateRangeField, SelectField, CheckboxGroupField...) khi user thao tác có thực sự gọi `useFilterStore().setXxx(...)` để ghi vào store, hay chỉ đổi local state nội bộ component mà không đẩy lên store dùng chung?

## Bước 2 — Sửa data flow gốc
- Đảm bảo MỌI component hiển thị số liệu (KpiCardGrid, MetricLineChart, DualAxisLineChart) chỉ nhận data qua props từ kết quả của `usePlatformDetailMetrics()` gọi ở `page.tsx` — không tự fetch, không dùng data tĩnh.
- `queryKey` phải là `['platform-detail', platform, appliedFilters]` (xem Bước 3 về `appliedFilters`), để mỗi filter khác nhau tạo cache riêng và tự động refetch khi filter đổi.
- Mọi `FilterField/*` phải ghi thay đổi vào `platform-filter-store.ts` đúng theo `key` khai báo trong `lib/config/filter-fields.ts` — kiểm tra lại từng field, không được có field nào chỉ đổi local state

## Bước 3 — Thêm nút "Xem báo cáo" (2-stage filter state)
Vì có 17 filter, KHÔNG tự động refetch ngay mỗi lần đổi 1 filter (sẽ gọi API liên tục, trải nghiệm giật). Tách state làm 2 tầng:
- `draftFilters`: filter đang chỉnh trong lúc user thao tác (Team, DateRange, Status, Campaign...) — đổi ngay khi user click/gõ, KHÔNG trigger fetch.
- `appliedFilters`: filter thực sự dùng để gọi API — chỉ cập nhật khi user bấm nút "Xem báo cáo".

Cách làm cụ thể trong `platform-filter-store.ts`:
```typescript
interface PlatformFilterState {
  draft: FilterValues;
  applied: FilterValues;
  setDraftField: (key: string, value: any) => void;
  applyFilters: () => void;   // copy draft -> applied, trigger refetch
}
```

`usePlatformDetailMetrics()` phải dùng `applied` (không phải `draft`) làm
`queryKey`. Thêm nút:
```tsx
// đặt cuối FilterPanel.tsx hoặc 1 vị trí nổi bật theo mockup (góc phải
// khu vực filter, ngang hàng Content code search)
<Button onClick={() => useFilterStore.getState().applyFilters()}>
  Xem báo cáo
</Button>
```

NGOẠI LỆ — 2 filter sau nên áp dụng ngay (auto-apply), không cần đợi nút, vì hành vi tự nhiên của user là "click vào là muốn xem ngay":
- Team Selector Grid (chọn team → tự apply luôn)
- Nếu muốn giữ đơn giản và nhất quán, có thể để CẢ Team cũng qua nút "Xem báo cáo" — tao ưu tiên phương án tất cả filter đều qua 1 nút duy nhất để hành vi dễ đoán, trừ khi mày thấy Team nên tách riêng.

## Bước 4 — Trạng thái khi chưa bấm "Xem báo cáo" lần đầu
- Lần đầu vào trang: tự động apply filter mặc định (VD 14 ngày gần nhất, tất cả team/campaign) để có báo cáo hiển thị ngay, không bắt user phải bấm nút mới thấy gì cả.
- Sau khi user đổi draft filter mà chưa bấm nút: có thể thêm 1 dấu hiệu nhỏ (VD nút "Xem báo cáo" đổi màu/có chấm cam) báo hiệu "có filter mới chưa áp dụng" — không bắt buộc, làm nếu không tốn nhiều effort

## Bước 5 — Kiểm thử
- Đổi Date Range -> bấm "Xem báo cáo" -> verify Network tab có gọi đúng 1 request `/api/v1/platform-detail` với query param date_from/date_to mới.
- Đổi 3-4 filter cùng lúc rồi mới bấm nút 1 lần -> verify chỉ gọi API 1 lần (không gọi lặp theo từng filter).
- Chọn Team ở lưới -> verify đúng theo quyết định ở Bước 3 (auto-apply hay qua nút, thống nhất 1 cách).
- Xoá hết filter (về "All") -> bấm "Xem báo cáo" -> verify ra đúng tổng số liệu toàn bộ account (168 dòng fact trong seed data mẫu).

Nếu đang dùng mock data (`lib/mock/platform-detail.mock.ts`) vì backend endpoint /api/v1/platform-detail chưa xong, giữ nguyên cơ chế mock nhưng đảm bảo mock function cũng nhận `appliedFilters` làm tham số và trả kết uả có filter thật sự (VD filter mock data theo date range được truyền vào) — để test được luồng UI ngay cả khi chưa có backend thật, tránh tình trạng mock luôn trả về data giống hệt nhau bất kể filter gì.