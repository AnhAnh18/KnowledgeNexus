# Foundation Primer M0-M4

Tài liệu này là bản nén kiến thức cho phần Foundation trước M5. Mục tiêu không phải thay thế contract, mà giúp bạn hiểu các milestone đã xây nền móng nào và vì sao code hiện tại được tách như vậy.

Nguồn chuẩn vẫn là:

- `contracts/foundation/schemas/`
- `contracts/foundation/CHUNKING_SPEC.md`
- `contracts/foundation/decision_logs/`
- `contracts/foundation/Task2_Task3_Integration_Contract.md`

## Bức tranh chung

Foundation là phần sản xuất dữ liệu tri thức. Nó crawl source, chuẩn hóa, chunk, tạo record, kiểm tra schema, rồi xuất snapshot JSONL. Foundation không embed, không ghi Qdrant, không retrieval, không chat.

Luồng đích:

```text
source systems
  -> Foundation crawl/raw/work
  -> normalized records
  -> data/exports/<dataset_name>/<dataset_version>/
  -> Indexing validates/imports
  -> Retrieval/Chat consume through Indexing
```

Boundary quan trọng nhất là export snapshot. Downstream chỉ đọc snapshot, không đọc `data/raw/` hoặc `data/work/`.

## M0 - Scaffold và ranh giới dự án

M0 dựng khung tối thiểu để code có chỗ đứng:

- package roots như `knowledgenexus.foundation` và `knowledgenexus.shared`;
- contract root ở `contracts/foundation/`;
- shared schema loader/validator ở `shared/contracts/foundation`;
- `.env.example` và ignore rule cho secret/runtime data.

Kiến thức cần nắm:

- Đây là modular monolith: Foundation, Indexing, Retrieval, Chat là bounded context trong cùng repo.
- Foundation có thể dùng `shared` và `contracts/foundation`, nhưng không import Indexing/Retrieval/Chat.
- Contract là boundary, không phải Python import boundary.

## M1 - Schema loader và validator

M1 thêm khả năng load schema và validate record/JSONL bằng JSON Schema.

File chính:

- `src/knowledgenexus/shared/contracts/foundation/contract_loader.py`
- `src/knowledgenexus/shared/contracts/foundation/schema_validator.py`

Ý nghĩa:

- `contracts/foundation/schemas` là sự thật cuối cùng về shape dữ liệu.
- Builder và exporter có thể đơn giản, nhưng trước khi ghi/import phải validate.
- `FoundationSchemaValidator.validate_record()` kiểm tra một object.
- `FoundationSchemaValidator.validate_jsonl_file()` đọc JSONL từng dòng và báo lỗi kèm file/line.

Điểm cần nhớ: schema validation là cổng an toàn giữa code và contract. Nếu code "có vẻ đúng" nhưng schema reject, schema thắng.

## M2 - Domain rules và record builders

M2 tạo các khối thuần domain để dữ liệu ổn định và deterministic.

Nhóm rule:

- `ContentHasher`: hash nội dung đã chuẩn hóa.
- `TextNormalizationRules`: chuẩn hóa text cơ bản.
- ID generators: document, chunk, relation, ACL, tombstone.
- `DatasetVersionGenerator` đến sau ở M3B nhưng cùng tinh thần deterministic.

Nhóm builder:

- `CanonicalDocumentRecordBuilder`
- `ChunkRecordBuilder`
- `RelationRecordBuilder`
- `ACLRecordBuilder`
- `ManifestRecordBuilder`

Builder chỉ tạo dict đúng schema-facing shape. Builder không crawl, không parse source, không chunk text thật, không gọi API, không validate toàn bộ JSON Schema bên trong.

Mẫu tư duy:

```text
caller supplies domain inputs
  -> builder creates schema-shaped dict
  -> validator proves contract compatibility
```

Điểm dễ nhầm:

- `ChunkRecordBuilder` không tự split text. Nó nhận `text`, `chunk_id`, `token_count`.
- `CanonicalDocumentRecordBuilder` không lưu raw body nếu schema không có field đó.
- `ACLRecordBuilder` nhận effective ACL đã được tính sẵn; nó không gọi Confluence permission API.

## M2D - Coherent sample set

Sau khi có builder riêng lẻ, M2D tạo một graph mẫu nhỏ nhưng nhất quán:

- document;
- chunks trỏ về document;
- relation trỏ tới entity hợp lệ;
- ACL trỏ về document;
- tất cả records validate bằng schema.

Ý nghĩa của M2D là kiểm tra cross-record invariant, không chỉ kiểm tra từng record đứng riêng.

## M3 - Export snapshot foundation

M3 biến record dict thành snapshot filesystem an toàn.

Các bước chính:

```text
M3A JsonlRecordWriter
  -> M3B DatasetVersionGenerator
  -> M3C ManifestRecordBuilder
  -> M3D FullSnapshotStagingWriter
  -> M3E FullSnapshotStagingCompleter
  -> M3F FullSnapshotPublisher
```

### M3A - JSONL writer

`JsonlRecordWriter` ghi record thành UTF-8 JSONL deterministic:

- giữ order do caller đưa vào;
- `sort_keys=True`;
- newline ổn định;
- không validate schema;
- không tạo manifest;
- không biết snapshot layout.

### M3B - dataset_version

Convention producer-side:

```text
vYYYYMMDD-HHMMSS-ffffffZ
```

Caller đưa timezone-aware `datetime`; generator convert sang UTC. Downstream coi version là opaque string, nhưng folder name, `manifest.dataset_version`, và `LATEST.txt` phải khớp.

### M3C - Manifest

Manifest mô tả snapshot:

- `dataset_version`;
- `export_mode`;
- `generated_at`;
- `config_hash`;
- `chunker_version`;
- `schemas_version`;
- `counts`.

Manifest không tự scan filesystem. Caller đưa counts, builder tạo dict, validator kiểm tra schema.

### M3D - Machine-readable staging

`FullSnapshotStagingWriter` tạo staging directory với:

- `documents.jsonl`
- `chunks.jsonl`
- `relations.jsonl`
- `acl.jsonl`
- `media_assets.jsonl`
- `symbols.jsonl`
- `sync_state.jsonl`
- `tombstones.jsonl`
- `manifest.json`

M3D validate từng record trước khi ghi. Nếu fail sau khi đã tạo staging, nó xóa staging do nó sở hữu.

### M3E - Quality report

`FullSnapshotStagingCompleter` thêm `quality_report.md` vào staging đã hợp lệ.

Nó không publish, không update `LATEST.txt`, không invent quality metrics chưa có evidence. Report hiện tại chỉ nói metadata và các check đã thực sự chạy.

### M3F - Publish và LATEST

`FullSnapshotPublisher` nhận staging complete, rename thành final version directory, rồi update `LATEST.txt` sau cùng.

Lý do update `LATEST.txt` cuối: consumer chỉ thấy snapshot mới khi final directory đã tồn tại và complete.

Nếu publish final directory xong nhưng update `LATEST.txt` fail, snapshot mới vẫn còn đó nhưng chưa được advertise. Operator hoặc task recovery sau xử lý, publisher không rollback tự động.

## M4 - Golden full snapshot

M4 commit một fixture snapshot synthetic để làm acceptance baseline.

Nó chứng minh:

- M3D -> M3E -> M3F tạo được tree hoàn chỉnh;
- output byte-identical khi input không đổi;
- JSONL records validate;
- manifest counts và file set khớp;
- fixture không phụ thuộc source thật, network, credential, hoặc environment.

M4 là "thước đo ổn định" cho exporter. Khi sau này code thay đổi, fixture giúp phát hiện thay đổi ngoài ý muốn ở format hoặc bytes.

## Các pattern nền

### Determinism

Cùng input phải ra cùng ID, hash, JSON bytes, version format, sort order. Điều này giúp skip re-embed, debug snapshot, và review diff.

### Fail closed

Khi shape không đúng, schema không khớp, path không an toàn, hoặc file set bất thường, code dừng thay vì đoán.

### Staging before publish

Snapshot được dựng trong staging trước, verify đủ file, rồi mới publish. Consumer không được nhìn thấy output dở dang.

### Contract-first

Schema quyết định field. Code không thêm field "cho tiện" nếu schema chưa có.

### Snapshot-only handoff

Indexing đọc export snapshot. Nó không đọc raw/work của Foundation, không re-chunk source Foundation đã export.

## Bạn nên tự giải thích được

Sau primer này, bạn nên giải thích được:

- Vì sao Foundation không ghi Qdrant.
- Vì sao record builder trả plain dict thay vì ORM/Pydantic model.
- Vì sao phải validate JSONL trước import.
- Vì sao `LATEST.txt` được update sau cùng.
- Vì sao M4 cần synthetic golden snapshot.
- Vì sao `ChunkRecord.text` downstream phải embed verbatim.
