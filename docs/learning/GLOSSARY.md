# Foundation Glossary

Glossary này gom các thuật ngữ đang lặp lại trong M0-M5. Định nghĩa ở đây phục vụ việc đọc code và review; nếu có mâu thuẫn field-level, schema trong `contracts/foundation/schemas/` thắng.

## Architecture

**Foundation**

Bounded context chịu trách nhiệm crawl, raw preservation, normalization, chunking, ACL, relation, media, symbol, tombstone, và export snapshot. Không embed, không retrieval, không chat.

**Indexing**

Consumer của Foundation snapshot. Nó validate, import, embed `ChunkRecord.text` verbatim, hydrate DB, và ghi vector store.

**Retrieval**

Đọc qua Indexing read ports để search/hydrate/enforce ACL trước khi trả kết quả.

**Chat**

Tầng dùng retrieval result đã qua ACL để tạo câu trả lời có citation. Chat không chạm raw Foundation hay Qdrant trực tiếp.

**Bounded context**

Một vùng ownership trong cùng repo. Boundary được giữ bằng dependency direction và contract, không nhất thiết bằng repo riêng.

**Clean Architecture**

Domain/application không phụ thuộc concrete infrastructure. Infrastructure implements ports. CLI/composition root lắp các mảnh lại.

**Port**

Interface/Protocol mô tả thứ application cần. Ví dụ `ConfluenceInventoryPort` nói "tôi cần metadata pages", không nói dùng HTTP thế nào.

**Adapter**

Concrete implementation của port. Ví dụ `ConfluenceDataCenterInventoryAdapter` gọi Data Center API rồi yield `ConfluencePageMetadata`.

**Transport**

Lớp thấp hơn adapter, chỉ biết HTTP/JSON/auth/error boundary. Transport không hiểu inventory policy.

**Composition root**

Nơi lắp concrete transport, adapter, use case, writer. M5C smoke runner là composition root.

## Contracts and Records

**Contract**

Tập tài liệu/schema quyết định boundary giữa Foundation và downstream. Contract không phải gợi ý; schema là nguồn chuẩn cho record shape.

**JSON Schema**

Machine-readable rule cho từng record. Validator dùng schema để reject dữ liệu sai trước khi export/import.

**JSONL**

Một JSON object mỗi dòng. Phù hợp cho stream record lớn mà không cần load toàn bộ file.

**CanonicalDocument**

Record đại diện document đã chuẩn hóa ở mức document. Nó không nhất thiết chứa toàn bộ raw body.

**ChunkRecord**

Record chứa text chunk sẽ được embed. `ChunkRecord.text` là verbatim input cho embedding downstream.

**RelationRecord**

Record mô tả quan hệ như mention Jira key, link page, embed media. Nó không tự crawl target.

**ACLRecord**

Record mô tả effective access tags. Retrieval phải enforce deny-safely trước khi trả kết quả.

**MediaAsset**

Record metadata/media processing output. Media binary/raw nằm ngoài JSONL; record giữ metadata/provenance/text extract nếu có.

**SymbolRecord**

Record cho code symbol/index lookup. Hiện còn deferred tới symbol track.

**SyncStateRecord**

Export/diagnostic view của crawl state. Mutable checkpoint thật về sau thuộc Foundation metadata store.

**TombstoneRecord**

Record thông báo entity bị xóa, revoked, out of scope, updated, hoặc invalidated để downstream xóa/invalidate đúng entity type.

**Manifest**

Record mô tả snapshot: version, mode, counts, config hash, chunker version, schema version.

**Quality report**

Human-readable report đi kèm snapshot. Không phải input chính cho Indexing.

## Snapshot and Storage

**Snapshot**

Một version export hoàn chỉnh dưới `data/exports/<dataset_name>/<dataset_version>/`.

**Dataset version**

Producer-side string dạng `vYYYYMMDD-HHMMSS-ffffffZ`. Consumer coi opaque nhưng yêu cầu folder, manifest, và `LATEST.txt` khớp.

**LATEST.txt**

Pointer tới snapshot version hiện tại. Được update sau khi final snapshot đã publish.

**Staging directory**

Thư mục tạm thuộc dataset root để dựng snapshot trước khi publish.

**Full snapshot**

Export đầy đủ hiện trạng trong scope. Delta/update propagation vẫn thuộc milestone sau.

**Delta snapshot**

Export thay đổi so với version trước, kèm tombstone. Chưa phải path hiện tại.

**Hydrate DB**

Database giữ full text và metadata để trả kết quả/citation sau vector search. Qdrant chỉ giữ slim payload.

**Vector store**

Qdrant hoặc tương đương. Chứa vector và payload filter tối thiểu, không phải source of truth.

## M5 Confluence Terms

**Inventory**

Danh sách page metadata trong một root scope: ID, title, ancestor path, version, labels, scope status. Chưa lấy body page.

**Scope**

Quyết định page nào included hoặc excluded subtree. M5 dùng explicit include roots và exclude subtrees bằng page ID.

**Root page**

Page cha được chọn làm điểm bắt đầu inventory.

**Descendant**

Page nằm dưới root. CQL `ancestor=<root>` trả descendants nhưng không trả root.

**CQL**

Confluence Query Language. M5B dùng root-scoped CQL để tìm descendants theo `space`, `ancestor`, và `type=page`.

**Data Center**

Confluence deployment family hiện đang target. Khác Confluence Cloud về API shape/path.

**Bearer PAT**

Personal Access Token dùng trong `Authorization: Bearer ...`. PAT chỉ đi qua environment/transport, không vào CLI args, logs, report, tests.

**Pagination**

API trả từng window theo `start`, `limit`, `size`, `totalSize`. Adapter advance bằng `start + size` sau khi parser validate window.

**Fail closed**

Khi dữ liệu/API/file không đúng contract, dừng với lỗi an toàn thay vì đoán tiếp.

**Sanitized packet**

Evidence từ máy có Confluence access đã xóa host, token, ID thật, title, identity, dynamic text. Dùng để thiết kế/test offline.

**Smoke runner**

CLI nhỏ để chạy live inventory an toàn trên máy có Confluence access. Nó compose production components và tạo summary không chứa metadata nhạy cảm.

## Security

**Secret**

PAT/token/password/cookie/authorization value. Không commit, không log, không đưa vào exception output.

**Sensitive scope data**

Host, space key, root page ID, page IDs, title/path thật. Có thể tồn tại trong private repo/contracts cũ, nhưng M5C summary không được chứa.

**No-clobber publish**

Publish không ghi đè file người khác đã tạo. Dùng để tránh race làm mất dữ liệu.

**Formula injection**

CSV cell bắt đầu bằng `=`, `+`, `-`, `@` có thể bị spreadsheet hiểu là formula. Report CSV phải neutralize presentation value.

## Review Words

**P0**

Blocker nghiêm trọng nhất: data loss lớn, security leak nghiêm trọng, không chạy được core path.

**P1**

Bug quan trọng cần sửa trước approve: race, false pass, leak credential, corrupt output.

**P2**

Vấn đề correctness/security thực tế nhưng ít cháy hơn P1. Thường vẫn chặn approve task.

**P3**

Nên sửa/ghi nhận, nhưng không nhất thiết chặn milestone nếu scope/risk thấp.

**Independent review**

Reviewer đọc repo và chạy test độc lập. Pass đầu tiên không sửa working tree.

**Review stack**

Nhiều commit nhỏ `[TASK-A]`, `[TASK-B]`, `[TASK-C]` để review, sau đó squash thành một task commit nếu cần lịch sử gọn.
