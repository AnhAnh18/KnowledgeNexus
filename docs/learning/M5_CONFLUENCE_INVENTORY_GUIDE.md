# M5 Confluence Inventory Guide

M5 là bước đưa Foundation từ exporter synthetic sang Confluence metadata thật, nhưng vẫn chưa crawl body page. Nó trả lời câu hỏi: "Trong wiki scope này có những page nào, cấu trúc cha-con ra sao, page nào nên include/exclude, và API Data Center trả shape gì?"

## M5 không làm gì

M5 không lấy page body, attachment, restriction, ACL thật, raw preservation, normalization, chunking, embedding, Qdrant, retrieval, hoặc chat.

Điều này cố ý. Trước khi crawl nội dung lớn, Foundation cần một inventory nhỏ, deterministic, và an toàn để người vận hành chọn scope.

## Luồng tổng thể

```text
Confluence Data Center API
  -> transport gets safe JSON
  -> adapter builds root/search requests
  -> mapper validates response shape
  -> ConfluencePageMetadata
  -> BuildConfluenceInventory
  -> ConfluenceInventoryItem
  -> pages_inventory.jsonl + inventory_report.csv
```

Ở M5C live smoke:

```text
env credentials
  -> UrllibConfluenceHttpTransport
  -> ConfluenceDataCenterInventoryAdapter
  -> BuildConfluenceInventory
  -> ConfluenceInventoryReportWriter
  -> m5c_smoke_summary.json
```

Smoke runner chỉ compose các component có sẵn. Nó không duplicate HTTP, CQL, pagination, mapping, scope, hay report serialization.

## M5A - Deployment-independent inventory core

M5A tạo domain/application core không biết Confluence triển khai bằng API nào.

File chính:

- `src/knowledgenexus/foundation/domain/models/confluence_source_config.py`
- `src/knowledgenexus/foundation/domain/models/confluence_page_metadata.py`
- `src/knowledgenexus/foundation/domain/models/confluence_inventory_item.py`
- `src/knowledgenexus/foundation/domain/rules/confluence_scope_policy.py`
- `src/knowledgenexus/foundation/ports/confluence_inventory_port.py`
- `src/knowledgenexus/foundation/application/use_cases/build_confluence_inventory.py`
- `src/knowledgenexus/foundation/infrastructure/exporters/confluence_inventory_report_writer.py`

### Ý tưởng chính

`ConfluenceSourceConfig` mô tả source:

- `source_id`;
- `space_key`;
- include roots;
- exclude subtrees;
- `page_size`.

`ConfluenceInventoryPort` là port mà use case cần:

```text
iter_page_metadata(space_key, root_page_id, page_size)
  -> ConfluencePageMetadata...
```

Use case không biết HTTP. Nó chỉ nhận metadata, validate rằng page đúng space/root, rồi áp scope policy.

### Scope policy

Scope hiện tại là explicit, không phải AI classifier:

- root trong `include_roots` được crawl;
- subtree trong `exclude_subtrees` bị đánh dấu excluded;
- còn lại included;
- page-tree bằng page ID là authority.

Rule-based relevance/labels chỉ là enrichment hoặc review hint, chưa phải cơ chế tự động loại wiki "không liên quan Knowledge".

### Report writer

M5A ghi hai file:

- `pages_inventory.jsonl`: machine-readable inventory.
- `inventory_report.csv`: human review report.

Các điểm an toàn đã được chốt:

- không overwrite target đã có;
- publish kiểu no-clobber để tránh race;
- CSV neutralize spreadsheet formula;
- JSONL giữ original values, CSV là presentation layer;
- `attachment_count=None` vì M5 chưa fetch attachment.

## M5B-0 - Offline API probe

M5B-0 không phải production connector. Nó là tool riêng dưới `.local_ai/` để chạy trên máy có Confluence access và thu sanitized evidence.

Mục đích:

- xác nhận Data Center endpoint/path/query shape;
- lấy response shape thật nhưng đã scrub;
- tránh Codex machine phải truy cập Confluence;
- thiết kế M5B-1/M5B-2 dựa trên evidence, không đoán.

Kết quả quan trọng đã học được:

- CQL `ancestor=<root>` trả descendants, không trả chính root.
- Root phải fetch riêng.
- Search response có `start`, `limit`, `size`, `totalSize`.
- Descendant result nằm trong `result.content`.
- Ancestor path có cả ancestors phía trên selected root, nên mapper phải trim từ selected root.
- Attachment count không có trong inventory response, nên M5 boundary dùng `None`.

Packet đã sanitize nên một số numeric như `totalSize` trong packet không replay trực tiếp được. Parser production dùng fixture synthetic nhất quán và trace request sequence làm evidence.

## M5B-1 - Response mapper

M5B-1 là pure parser/mapper. Không HTTP, không env, không credential, không CQL loop.

File chính:

- `src/knowledgenexus/foundation/infrastructure/confluence/confluence_data_center_page_metadata_mapper.py`
- fixtures dưới `tests/fixtures/foundation/confluence_data_center/`
- tests mapper dưới `tests/foundation/infrastructure/confluence/`

### map_root

Root payload được normalize thành `ConfluencePageMetadata`:

- ID phải match expected root;
- `type=page`, `status=current`;
- version shape hợp lệ;
- nếu `space.key` có mặt thì phải match expected space;
- nếu `space` vắng mặt thì dùng expected space từ caller;
- labels optional và normalize thành `()`.

Root luôn có:

- `parent_page_id=None`;
- `ancestor_page_ids=()`;
- `ancestor_titles=()`.

### map_search_result

Descendant result strict hơn:

- result phải có `content`;
- content ID không được là selected root;
- space phải match;
- ancestors phải chứa selected root đúng một lần;
- ancestor path được trim từ selected root trở xuống;
- duplicate ancestor IDs và self-ancestry bị reject;
- labels required theo shape search đã xác nhận.

### parse_search_page

Parser validate numeric envelope:

- response `start` match request start;
- response `limit` match request limit;
- `size == len(results)`;
- `size <= limit`;
- `totalSize` cover current window;
- non-terminal page phải advance.

Terminal condition:

```text
start + size >= totalSize
```

Adapter không dùng `_links.next` để drive loop; nó advance từ numeric envelope đã validate.

## M5B-2 - Data Center HTTP adapter

M5B-2 là production implementation của inventory port cho Confluence Data Center.

File chính:

- `src/knowledgenexus/foundation/infrastructure/confluence/confluence_http_transport.py`
- `src/knowledgenexus/foundation/infrastructure/confluence/confluence_data_center_inventory_adapter.py`
- tests fake HTTP tương ứng.

### Transport

`UrllibConfluenceHttpTransport` chịu trách nhiệm:

- HTTPS-only base URL;
- Bearer PAT header;
- timeout;
- response-size limit;
- redirect refusal;
- JSON content checks;
- sanitized error messages.

Transport không biết inventory, root, CQL, scope, hoặc page metadata.

### Adapter

`ConfluenceDataCenterInventoryAdapter` chịu trách nhiệm:

- validate `space_key`, `root_page_id`, `page_size`;
- fetch root riêng bằng `/rest/api/content/{page_id}`;
- require root `space.key` có mặt và match configured space;
- yield root trước;
- search descendants bằng `/rest/api/search`;
- CQL: `space="<space>" and ancestor=<root> and type=page`;
- expand descendant metadata đủ cho mapper;
- paginate bằng `start + size`;
- dừng nếu parser nói terminal;
- fail nếu vượt `max_search_pages`.

Root request dùng `expand=space,version`. Đây là additive shape chưa được M5B-0 xác nhận trực tiếp; M5C live smoke là nơi xác nhận.

### Vì sao cần max_search_pages

Nếu API/search shape thay đổi hoặc pagination không terminal, loop không được chạy vô hạn. `max_search_pages` là explicit budget do caller chọn, không có magic default.

## M5C - Safe live smoke

M5C-1 thêm smoke runner offline-tested. M5C-2 là lần chạy thật trên máy có Confluence access.

File chính:

- `src/knowledgenexus/foundation/cli/confluence_inventory_smoke.py`
- `docs/runbooks/M5C_CONFLUENCE_INVENTORY_SMOKE.md`
- `tests/foundation/cli/test_confluence_inventory_smoke.py`

### Credential boundary

Credential chỉ đến từ environment:

- `CONFLUENCE_BASE_URL`
- `CONFLUENCE_PAT`

Không có PAT CLI flag. `.env` không auto-load. Parse error không echo argv để tránh in nhầm token/base URL/page ID.

### Output boundary

`--output-dir` phải:

- tồn tại;
- là directory;
- rỗng;
- nằm ngoài repo.

Output thành công gồm đúng:

- `pages_inventory.jsonl`;
- `inventory_report.csv`;
- `m5c_smoke_summary.json`.

Summary không chứa host, PAT, space key, root page ID, page IDs, title, path, hoặc CQL. Nó chỉ chứa counts, booleans, limits, và hashes.

Failure không tạo passed summary. Failure chỉ in JSON sanitized với category.

## Những API contact hiện có

M5B-2 production adapter hiện dùng hai request shape:

```text
GET /rest/api/content/{page_id}?expand=space,version
GET /rest/api/search?cql=space="<space>" and ancestor=<root> and type=page&expand=content.ancestors,content.space,content.version,content.metadata.labels&limit=<page_size>&start=<start>
```

Không có request page body, attachment, restriction, permission, comment, export, hay rendered HTML.

API result không được lưu raw trong production M5. Production M5 chỉ lưu normalized inventory reports. Sanitized API packets của M5B-0 nằm dưới `.local_ai/evidence/` và không phải runtime output.

## Các test bảo vệ điều gì

M5A tests:

- config/model validation;
- scope policy;
- use case root/space containment;
- report writer bytes/race/formula safety.

M5B-1 tests:

- root fallback/match/mismatch;
- descendant shape;
- ancestor trim;
- label envelope;
- numeric pagination;
- sanitized fixture safety.

M5B-2 tests:

- transport URL/auth/JSON/error boundary;
- adapter request sequence;
- root-first output;
- root-space fail closed;
- bounded pagination;
- no live network.

M5C tests:

- CLI validation;
- credential/env boundary;
- output-dir safety;
- no sensitive summary;
- success-only summary;
- cleanup only owned files;
- fake/offline execution.

## Cách đọc code theo lớp

Nếu bạn muốn debug một inventory run, đọc theo thứ tự này:

1. `confluence_inventory_smoke.py`: args/env/output và composition.
2. `confluence_data_center_inventory_adapter.py`: request sequence và pagination.
3. `confluence_http_transport.py`: HTTP/auth/error details.
4. `confluence_data_center_page_metadata_mapper.py`: response shape validation.
5. `build_confluence_inventory.py`: root/space containment và scope policy.
6. `confluence_inventory_report_writer.py`: report publication.

Nếu lỗi là API shape, thường nằm ở mapper/adapter. Nếu lỗi là file/report, thường nằm ở writer/smoke runner. Nếu lỗi là page bị include/exclude sai, xem source config và scope policy trước.

## Điều M5 chuẩn bị cho M6

Sau M5C live smoke, ta có:

- root request confirmed hay chưa;
- descendants count nhỏ có đúng kỳ vọng không;
- page tree/ancestor path có đúng không;
- report để chọn explicit exclude subtrees;
- confidence rằng production adapter có thể lấy metadata an toàn.

M6 mới bắt đầu một-page vertical slice:

- fetch raw page;
- preserve raw provenance;
- capture restrictions/attachment metadata;
- normalize one page;
- chunk one page;
- materialize ACL/relation;
- export one real snapshot through M3.

## Bạn nên tự giải thích được

Sau M5 guide này, bạn nên giải thích được:

- Vì sao root phải fetch riêng.
- Vì sao CQL descendants không đủ để pass M5A root invariant.
- Vì sao mapper strict nhưng root labels optional.
- Vì sao adapter không dùng `_links.next`.
- Vì sao `max_search_pages` bắt buộc.
- Vì sao smoke summary không chứa page metadata.
- Vì sao M5 chưa tự động lọc wiki không liên quan bằng AI.
- Vì sao output thật của M5C phải nằm ngoài repo.
