# Báo cáo trạng thái Foundation Confluence

Ngày tổng hợp: 2026-08-18
Phạm vi: Confluence text-first, ACL, relations và Draw.io

## Trạng thái tổng quan

Foundation Confluence đã hoàn thành implementation bounded và kiểm thử offline.
Chưa thể tuyên bố `DONE` production vì chưa có nghiệm thu real Root-1/second
sync, closeout W5 và các gate vận hành W6.

## Đã hoàn thành

| Nhóm | Kết quả đã có |
|---|---|
| Inventory và capture | Data Center inventory, pagination, raw-page capture, checkpoint, replay, retry/rate limit và single-writer control. |
| Xử lý nội dung | Normalization/chunking cho text, heading, list, code block, table và nested table; deterministic IDs/order. |
| Bảo mật và provenance | ACL metadata, relation ownership, Jira/page/media relations, fail-closed validation và sanitized observability. |
| Draw.io | Parsed Draw.io tạo searchable `content_kind: diagram` chunks; strict export có Mermaid `.mmd` bounded. |
| Full snapshot | Deterministic staging, strict readback, atomic publication và `LATEST.txt` cập nhật cuối cùng. |
| Delta | Base binding, sparse delta, tombstone cascade, ACL-only re-emission và second-sync orchestration. |
| URL operation | Full/short URL được duyệt, start/resume/status, unique compatible resume, phase sequencing và aggregate progress. |
| Kiểm thử | Foundation/Indexing integration `239 passed`; URL/packet/Draw.io regression `163 passed`; có adversarial tests cho runtime type, XML, counter, hash và partial packet. |

## Chưa hoàn thành và yêu cầu để đóng

### 1. W5-B — Root-1 full snapshot thật

Yêu cầu:

- Chạy guarded one-shot với private operator configuration.
- Tuân thủ rate limit, request budget và single-writer rule.
- Xuất strict immutable full snapshot; verifier PASS trước khi `LATEST.txt` đổi.
- Chỉ lưu/return aggregate evidence đã sanitize.
- Owner chấp nhận W5-B receipt trước khi chạy bước tiếp theo.

Phương án: chạy theo W5-B runbook trên Root-1 với cấu hình private đã preflight;
thu receipt tổng hợp, kiểm tra publication/readback rồi xin owner xác nhận PASS.

### 2. W5-C — Second sync delta thật

Yêu cầu:

- Dùng snapshot W5-B đã được chấp nhận làm base.
- Chứng minh các trường hợp unchanged, changed, added, source-deleted và
  access-revoked theo runbook.
- Delta phải đúng base binding; tombstone đúng loại và không có record ngoài
  phạm vi.
- Controlled stop/resume không được refetch committed work.
- Owner chấp nhận W5-C receipt.

Phương án: chuẩn bị một tập thay đổi nhỏ, kiểm soát được trên Root-1; chạy
second sync theo W5-C runbook, đối chiếu delta/tombstone với expected change set
và chỉ chấp nhận khi base binding cùng resume counters khớp.

### 3. W5-D — Closeout

Yêu cầu:

- Reconcile aggregate evidence của W5-B và W5-C.
- Cập nhật trạng thái tài liệu theo evidence đã chấp nhận.
- Chạy consolidated independent review và nhận owner closeout.
- Freeze baseline sau W5; không tuyên bố recurring readiness chỉ từ W5.

Phương án: tổng hợp hai sanitized receipts vào checklist closeout, reconcile
roadmap/state, rồi dùng một phiên review độc lập để xác nhận không còn gate W5
mở trước khi owner đóng milestone.

### 4. W6-C — Automatic supervision

Yêu cầu:

- Chỉ restart các lỗi đã phân loại recoverable.
- Có finite restart budget và trạng thái exhausted-budget đã sanitize.
- Auth, authorization, scope, schema, corruption, provenance và ambiguous run
  phải dừng để operator xử lý, không tự restart.
- Chứng minh graceful stop, forced interruption và power-loss recovery.

Phương án: thêm supervisor hữu hạn bao quanh operator hiện có, dùng failure
taxonomy để quyết định `retry`, `resume` hoặc `operator_action`; lưu restart
budget trong durable state và kiểm thử fault injection tại từng phase boundary.

### 5. W6-D — Recurring Root-1 và HQ

Yêu cầu:

- Manual/scheduled sync dùng chung scope, checkpoint và delta rules.
- Trigger mới phải defer khi scope có active writer.
- Root-1 và HQ phải có run/raw/publication state độc lập.
- Chứng minh deterministic publication, interruption/resume và real second-sync
  delta cho từng root.

Phương án: dùng scheduler mỏng chỉ phát trigger; mọi trigger vẫn đi qua
single-writer lock, scope fingerprint và durable resume hiện có. Rollout Root-1
trước, quan sát một chu kỳ full/delta ổn định, sau đó mới bật HQ với workspace
và lịch chạy độc lập.

## Điều kiện tuyên bố Foundation Confluence DONE

Chỉ tuyên bố `DONE` khi W5-B, W5-C và W5-D đã được chấp nhận; W6-C/W6-D đã
được chứng minh cho Root-1 và HQ; và real full/delta publication có evidence đã
sanitize.

Indexing/Qdrant activation, SnapshotReady consumer và end-to-end
acknowledgement thuộc I1-I5. Chúng không chặn `Foundation Confluence DONE`,
nhưng chặn `Foundation-to-Indexing end-to-end DONE`.

## Hạng mục deferred và phương án unblock

Ba hạng mục dưới đây không chặn Foundation Confluence text + Draw.io `DONE`.
Chúng chỉ được mở lại khi có đủ đầu vào và acceptance gate riêng.

### 1. OCR/PDF/image/audio/video và generic binary media

Hiện trạng:

- Draw.io là media type đang nằm trong phạm vi chính và đã có searchable chunks.
- PDF/OCR đã có một số contract, policy seam và offline processor, nhưng chưa có
  production engine/model approval hoặc real media acceptance.
- Audio/video và generic binary media chưa thuộc production scope hiện tại.

Điều kiện unblock:

- Owner phê duyệt từng media type và engine/runtime/model tương ứng.
- Chốt MIME allowlist, file/count/size/time/memory budgets và quarantine policy.
- Có sanitized representative corpus gồm success, malformed, encrypted,
  oversized, unsupported và low-quality cases.
- Chốt quality metrics theo media type: extraction coverage, OCR accuracy,
  layout preservation, timeout/error rate và fallback/manual-review threshold.
- Xác định ACL inheritance, provenance, content-safety và retention rules cho
  binary input và extracted output.

Phương án:

1. Mở PDF text extraction trước vì deterministic và dễ kiểm soát hơn OCR.
2. Sau đó activate một OCR engine đã pin version/model; chạy offline acceptance
   trước khi cho phép production capture.
3. Mỗi media type dùng adapter riêng nhưng xuất về canonical document/chunk
   boundary chung; failure của một asset không được tạo partial authoritative
   output không được khai báo.
4. Thêm per-asset budgets, sandbox/quarantine, sanitized counters và adversarial
   tests cho malformed binary, decompression bomb, wrong MIME và engine timeout.
5. Chỉ mở audio/video sau khi PDF/OCR quality và resource gates ổn định.

Kết quả cần đạt: mỗi media type có contract, engine approval, bounded resource
profile, sanitized real-corpus PASS và independent review riêng.

### 2. 100k performance optimization

Hiện trạng:

- 10k correctness/repeatability đã PASS.
- 100k gate được defer; hiện chưa có claim về production throughput, RSS, disk
  growth hoặc completion time ở quy mô này.
- Việc defer 100k không làm giảm correctness gate của Root-1/HQ bounded rollout.

Điều kiện unblock:

- Có 100k synthetic hoặc sanitized production-like dataset với distribution rõ
  về depth, page size, tables, attachments, ACL và change rate.
- Chốt acceptance budgets cho wall time, requests/minute, peak RSS, disk usage,
  checkpoint size, restart time và delta completion time.
- Có môi trường đo ổn định và baseline hardware/runtime profile.
- Có quyền chạy load test mà không ảnh hưởng Confluence production service.

Phương án:

1. Đo baseline theo từng phase: inventory, capture, normalization/chunking,
   Draw.io và export; không tối ưu dựa trên tổng thời gian mơ hồ.
2. Profile CPU, memory, SQLite/checkpoint growth, filesystem I/O và object
   retention; xác định bottleneck bằng số liệu.
3. Tối ưu offline processing/batching trước. HTTP concurrency chỉ thay đổi sau
   khi có rate-limit contract và server-capacity approval riêng.
4. Chạy bậc thang 10k → 25k → 50k → 100k, có stop budget và regression check
   ở mỗi bậc.
5. Sau mỗi tối ưu, chạy lại determinism, replay, single-writer và failure tests
   để bảo đảm performance không làm đổi output/correctness.

Kết quả cần đạt: 100k run nằm trong budgets đã duyệt, deterministic/replay PASS,
không vượt server rate policy và có báo cáo capacity cùng independent review.

### 3. PLM ingestion

Hiện trạng:

- PLM đang `HOLD` và không có crawler/adapter production được phép hoạt động.
- Chưa có sanitized real response fixtures đủ để xác định schema, pagination,
  permissions, attachment và retry semantics.
- Không được suy diễn API contract chỉ từ mô tả tool hoặc tài liệu không đủ mẫu.

Điều kiện unblock:

- Owner cho phép read-only discovery đối với PLM.
- Có sanitized success/error responses đại diện và nhiều page/call để xác định
  pagination, truncation và stable identity.
- Xác minh field semantics cho ID, revision/version, timestamps, lifecycle,
  permissions, links/relations và attachment metadata.
- Xác minh auth/authorization failure, rate limit, retry-after, timeout và
  deletion/revocation behavior.
- Chốt source scope, ACL mapping, data retention và loại nội dung được phép
  đưa vào snapshot.

Phương án:

1. Thực hiện read-only contract discovery và lưu fixtures đã sanitize; chưa
   triển khai bulk ingestion ở bước này.
2. Viết typed response models/parser với fail-closed validation và pagination
   tests từ fixtures đã xác minh.
3. Thiết kế PLM adapter tái sử dụng canonical Foundation records, snapshot,
   checkpoint, retry và publication boundaries; không tạo pipeline song song.
4. Chạy offline fixture acceptance, sau đó bounded live smoke trên scope nhỏ.
5. Chỉ mở attachment/bulk traversal sau khi identity, ACL, retry và deletion
   semantics đã PASS independent review.

Kết quả cần đạt: API contract dựa trên evidence, read-only adapter bounded,
ACL/provenance đúng, live smoke đã sanitize PASS và owner phê duyệt mở rộng scope.

## Tài liệu vận hành

- `docs/runbooks/W5_A_REAL_INPUT_ACCEPTANCE.md`
- `docs/runbooks/W5_B_ROOT1_FULL_SNAPSHOT.md`
- `docs/runbooks/W5_C_SECOND_SYNC_DELTA.md`
- `docs/runbooks/CONFLUENCE_TEXT_DEMO.md`
- `.local_ai/ROADMAP.md`
- `.local_ai/IMPLEMENTATION_STATE.md`
