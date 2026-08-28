# Runbook — Ingest & Sync live một root Confluence lớn (tới 5.000 trang)

Runbook này mô tả luồng chạy trực tiếp trên portal (`start.bat` → http://127.0.0.1:8000),
dành cho trường hợp cần index một cây trang lớn rồi giữ cho index đó bám sát nguồn.

## 1. Ba nút, ba việc khác nhau

| Nút | Endpoint | Có sửa index không? |
| --- | --- | --- |
| 🚀 Bắt đầu Ingest | `POST /api/v1/ingest-jobs/confluence-subtrees` | Có — index (upsert) toàn bộ cây trang |
| 🔎 Kiểm tra thay đổi | `POST .../confluence-subtrees/sync-preview` | **Không** — chỉ crawl inventory và báo số liệu |
| ✅ Áp dụng đồng bộ | `POST .../confluence-subtrees/sync-apply` | Có — index phần mới/đổi **và xoá** phần đã bị xoá ở nguồn |

Nút "Áp dụng đồng bộ" chỉ hiện trên card của một job preview đã hoàn tất và
thực sự phát hiện thay đổi.

## 2. Vì sao cần `sync-apply` chứ không chạy lại ingest

Chạy lại ingest sẽ upsert đúng các trang mới và trang sửa đổi, nhưng **không bao giờ**
phát hiện được trang đã bị xoá: một packet chỉ mô tả những gì còn tồn tại.
`sync-apply` so packet vừa publish với packet đã publish gần nhất của cùng root, rồi:

- trang mới / trang đổi `source_version` → xoá bản cũ rồi embed + lưu bản mới;
- trang biến mất khỏi nguồn → tombstone (xoá chunks, vectors và dòng document);
- trang không đổi → **bỏ qua khâu embedding**.

Khâu embedding là phần lâu nhất của pipeline (máy demo chạy `EMBEDDING_DEVICE=cpu`),
nên đây là chỗ tiết kiệm thời gian thật sự ở lần chạy thứ hai trở đi.

Lưu ý về giới hạn: hợp đồng của Foundation ràng buộc một lần capture vào **toàn bộ**
inventory mà nó đã crawl, nên `sync-apply` vẫn crawl và fetch lại cả cây trang.
Không thể thu hẹp phần crawl xuống chỉ các trang đã đổi. Đây là "Approach A".
Khả năng crawl tăng dần (chỉ fetch trang đổi/mới) đã được khảo sát ở
[docs/LIVE_SYNC_APPROACH_B_SURVEY.md](../LIVE_SYNC_APPROACH_B_SURVEY.md) —
kết luận: cần đụng contract Foundation (raw-generation), rủi ro cao, chưa làm.

## 3. Baseline được tìm như thế nào

Baseline = workspace **đã publish packet** gần nhất cho đúng bộ ba
`(base_url, space_key, root_page_id)`, tìm bằng cách quét `CONFLUENCE_SNAPSHOT_ROOT`
chứ không tra bảng job. Nhờ vậy baseline vẫn đúng sau khi DB job bị reset, và URL rút gọn
(`/x/TOKEN`) hay `viewpage.action?pageId=` đều quy về cùng một root.

Nếu chưa từng có packet nào cho root đó:

- `sync-preview` trả `status = baseline_required` (UI cảnh báo màu vàng, không tính được số trang bị xoá);
- `sync-apply` sẽ index toàn bộ packet như một lần ingest đầu tiên và không xoá gì cả.

## 4. Chạy root lớn và xử lý khi lỗi

1. Đặt trong `.env`: `CONFLUENCE_MAX_PAGES=5000` (đây cũng là trần cứng của pipeline)
   và `CONFLUENCE_SNAPSHOT_ROOT` trỏ ra ngoài repo (ví dụ `D:/KnowledgeNexus_Data/confluence-snapshots`).
2. Bấm Ingest. Job chạy tuần tự qua các phase, card hiển thị `Step X/N` và số trang đã capture.
3. Nếu cần dừng: `⏸ Pause job`. Job dừng ở ranh giới phase kế tiếp (không tức thì).
4. Khi job **FAILED (resumable)** hoặc **PAUSED**: sửa nguyên nhân (mạng, PAT, dung lượng đĩa…)
   rồi bấm `↻ Resume job`. Resume dùng lại đúng workspace cũ nên các batch đã commit
   được replay chứ không crawl lại.
5. Resume giữ nguyên loại job: một `sync-apply` resume vẫn là `sync-apply`, không tụt về
   ingest thường (nếu tụt, bước tombstone sẽ bị bỏ qua âm thầm).

## 5. Cửa sổ rủi ro cần biết

`sync-apply` xoá các trang đã đổi **trước** khi ghi bản thay thế — bắt buộc, vì một
bản revision ngắn hơn sẽ để lại chunks thừa mà không gì dọn được. Nếu job chết đúng
trong khoảng đó, các trang ấy tạm thời biến mất khỏi index cho tới khi resume.
Lúc đó packet đã publish rồi, nên resume bỏ qua toàn bộ phần crawl và chỉ chạy lại phần index.

## 6. Số liệu trên card

`new_pages` / `changed_pages` / `deleted_pages` / `unchanged_pages` là kết quả diff.
Với job apply có thêm `tombstoned_pages` (số trang đã gỡ khỏi index) và
`chunks_ingested` (số chunk đã embed — chỉ đếm phần mới/đổi).
