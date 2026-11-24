---
name: feishu_doc
description: Read and edit Feishu documents by H2 section with mandatory read-back verification.
requires_tools: [feishu_doc]
min_nextloop: 1.1.0rc1
---

# Feishu Document Section Editing Skill

1. Inspect document structure first via `feishu_doc(action="read", doc_token="<token>")` unless the exact `## H2` heading is already given in `[Document Anchor Context]`.
2. Update only the target section with `feishu_doc(action="replace_section", doc_token="<token>", heading="<H2 title>", content="<updated body without ## heading line>")`.
3. Never modify neighboring sections unless explicitly asked. If `feishu_doc` reports a read-back error, report the failure honestly without claiming the document was updated.
