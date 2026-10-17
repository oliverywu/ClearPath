# Evidence and synthetic data

The packaged trial, product, enrollment, routes, lead times, most regulatory requirements and planted events are deterministic synthetic demonstration records. They are not verified legal research. Synthetic citation URLs identify fixture provenance and are not evidence that an authority published the simulated requirement.

A deliberately narrow evidence slice replaces one rule for each of the United States, EU/Germany, Canada and Japan with a cited official record. Those records preserve a short exact excerpt, retrieval and verification timestamps, effective interval, confidence and normalization notes. The Japan language record uses the ministry's English translation. Six additional Japan Article 16 candidates cite the current official Japanese consolidation and retain Japanese excerpts for label contents, prohibited claims, foreign-sponsor identification, emergency unblinding, packaging integrity, and product-control records/procedures. Those candidates remain `needs_review` pending qualified translation, scope, and applicability review. This focused slice demonstrates the evidence model; it does not convert the wider 24-country fixture into validated regulatory guidance.

Other source documents supplied with the repository inspired the workflow but remain research leads whose legal interpretations have not been adopted as verified rules. Future-effective versions are selected only when the dataset's planning date falls within their interval.

Four visible evidence distinctions are preserved:

- **Verified:** a human-reviewed rule backed by a non-synthetic source.
- **Needs review:** a collected or imported candidate that is not used as an approved regulatory fact.
- **Authoritative secondary:** source provenance indicating a secondary interpretation; independent from the rule's review state.
- **Synthetic:** a deliberate simulated input used for the demo.

Every atomic rule retains its jurisdiction, rule type, requirement key, operator, value, effective interval, source URL, title, exact excerpt, retrieval timestamp, confidence, source tier and review status. An import cannot label a synthetic source as verified. Current and future versions are retained rather than overwriting historical scenario inputs.

Teammates should provide exact source excerpts and complete citations, default new research to `needs_review`, and have a qualified reviewer validate translations and interpretation before marking a record `verified`. AI-extracted candidates are always forced to `needs_review`, and their quotations must occur verbatim in the saved snapshot before import preview. Source snapshots retain a content hash and raw diff; semantic change analysis preserves exact before/after citations. Neither a text diff nor AI-proposed materiality establishes an effective regulatory change. A named reviewer must confirm the normalized event before deterministic impact analysis.

No application output is regulatory or legal advice. The local app supports review and planning decisions by qualified users.
