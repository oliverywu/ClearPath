# Architecture and operational boundaries

Cleared for Takeoff runs entirely on a laptop. `start.py` starts a Python API on loopback port 8000, then serves the buildless browser app on port 3000 with a same-origin `/api` proxy. Runtime dependencies are Python's standard library only. This deliberately replaces the plan's suggested Next.js/FastAPI stack to make clean-clone startup independent of package downloads and native compilation.

`packages/domain` validates input records. `packages/planner` contains pure deterministic functions for effective rule selection, label compatibility, business-day milestone dependencies, schedule slack, temperature checks, change impact and comparisons. It has no HTTP, database, LLM or vendor dependency. Inputs and results carry a calculation version and evidence references.

`apps/api` persists validated datasets, immutable scenario payloads and the corresponding input snapshot in SQLite. Approvals and rejections are separate decisions. Database triggers protect scenario and audit records from in-place updates. A comparison uses the stored snapshots, so future imports cannot change what an earlier decision meant.

`packages/ingestion` owns source fetching, snapshots, content hashes, metadata extraction and candidate-rule normalization. Source content is evidence, never executable instructions. A source diff does not automatically declare a legal change verified. Human-reviewed atomic rules enter through preview and commit.

The planned AI research layer belongs between source collection and human evidence review. It may extract structured candidate rules, compare source versions, translate passages, classify likely material changes and prepare proposed change events. Every AI-derived record must retain its exact supporting excerpt and remain `needs_review`. AI output cannot write directly to the accepted rule set or bypass deterministic validation.

`packages/feature_provider` provides a common application contract for deterministic local and Chalk features. Provider failures retain local results and disclose the fallback. Rules, dates, group membership and approval decisions remain deterministic even when a remote provider is configured. `chalk/` defines the deployment-side feature namespace contract.

The assistant reads scenario objects and their source references. It explains stored values and refuses legal conclusions and plan-changing actions. A planned allowlisted what-if tool may translate supported questions into temporary scenario inputs, but the deterministic planner will still calculate the result and the assistant will remain unable to persist or approve it. Answers are usable without any model credentials.

Calendar export is an explicit action available for approved scenarios. Stable milestone UIDs make repeated export predictable. The `CalendarProvider` protocol defines future synchronization. Calendar and notification failures do not affect a decision or stored plan. Photon remains a disabled notification boundary until its service contract is available.

## Time and reproducibility

Each dataset supplies its own planning date. This makes demonstrations repeatable even as the laptop clock advances. Operational audit timestamps use UTC. Rule effective intervals use an inclusive start and exclusive end. Business-day calculations exclude weekends and configured jurisdiction holidays; holidays are data, not assumed legal calendars.

## Local trust model

This is a single-user local decision-support product. By default, both services bind to `127.0.0.1`. Reviewer names are audit attribution, not identity authentication. It is not a multi-user production authorization system. Source records and simulated assumptions remain visibly marked. No patient data is needed.

## Replacement data

Data is a versioned JSON record set, not application code. Replace product, trial, jurisdiction, site, depot, demand, route, rule, event and configuration records together through dataset preview and commit. Regulatory-only research uses the atomic rule import. Both boundaries validate references and provenance before activating records; imports generate proposed plans for review.
