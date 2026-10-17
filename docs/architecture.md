# Architecture and operational boundaries

Cleared for Takeoff runs entirely on a laptop. `start.py` starts a Python API on loopback port 8000, then serves the buildless browser app on port 3000 with a same-origin `/api` proxy. Runtime dependencies are Python's standard library only. This deliberately replaces the plan's suggested Next.js/FastAPI stack to make clean-clone startup independent of package downloads and native compilation.

`packages/domain` validates input records. `packages/planner` contains pure deterministic functions for effective rule selection, label compatibility, business-day milestone dependencies, schedule slack, temperature checks, change impact and comparisons. It has no HTTP, database, LLM or vendor dependency. Inputs and results carry a calculation version and evidence references.

`apps/api` persists validated datasets, immutable scenario payloads and the corresponding input snapshot in SQLite. Approvals and rejections are separate decisions. Database triggers protect scenario and audit records from in-place updates. A comparison uses the stored snapshots, so future imports cannot change what an earlier decision meant.

`packages/ingestion` owns source fetching, snapshots, content hashes, metadata extraction and candidate-rule normalization. Source content is evidence, never executable instructions. A source diff does not automatically declare a legal change verified. Human-reviewed atomic rules enter through preview and commit.

The Requirements screen shows every dated record, including review-gated candidates. Official-source candidates awaiting review are sorted first and called out explicitly; their exact excerpt and authority link are inspectable, while the planner continues to select only verified or explicitly synthetic inputs. This prevents newly collected legal text from silently changing an approved calculation.

`packages/research` implements the optional AI research layer between source collection and human evidence review. It uses the OpenAI Responses API with strict JSON Schema output and storage disabled. Requirement extraction is normalized with registered source metadata, checked for a verbatim quotation in the saved snapshot, validated against the domain schema, and forced to `needs_review`. Invalid or unsupported candidates are returned as errors and cannot enter an import preview.

Semantic change analysis compares the newest two immutable snapshots for one jurisdiction. The saved analysis includes the raw unified diff, exact before/after citations, proposed materiality, affected jurisdictions, likely requirement keys, ambiguity note, and normalized event. It remains a preview until a named reviewer records a confirmation note. Only the confirmed event can enter the deterministic planner. Provider failures create neither rules nor events.

`packages/feature_provider` provides a common application contract for deterministic local and Chalk features. Provider failures retain local results and disclose the fallback. Rules, dates, group membership and approval decisions remain deterministic even when a remote provider is configured. `chalk/` defines the deployment-side feature namespace contract.

The assistant reads scenario objects and their source references. It explains stored values and refuses legal conclusions and plan-changing actions. Its allowlisted what-if path translates supported questions into temporary scenario inputs, calls the deterministic planner, and returns a comparison without saving or approving the result. Answers are usable without any model credentials.

Calendar export and direct Google Calendar or Microsoft Graph synchronization are explicit actions available only for approved scenarios. Stable ICS milestone UIDs and deterministic Google event IDs make repeated export predictable. Tokens remain server-side; sync results are audited. Calendar and notification failures do not affect a decision or stored plan. Photon 2.0 is an optional coordination adapter: it creates or resolves a recipient, opens a messaging space, submits an alert, and can post a grounded follow-up reply. HTTP 202 is recorded as accepted rather than delivered, every result is audited, and dashboard state remains authoritative when Photon is unavailable.

Scenario comparison returns changed countries and milestones. The browser uses that set to show affected shipments and intersecting label groups first, while an explicit “Show full plan” control preserves complete audit access. `evals/gold.json` is the versioned evaluation source for local regression and Chalk Agent Evals.

## Time and reproducibility

Each dataset supplies its own planning date. This makes demonstrations repeatable even as the laptop clock advances. Operational audit timestamps use UTC. Rule effective intervals use an inclusive start and exclusive end. Business-day calculations exclude weekends and configured jurisdiction holidays; holidays are data, not assumed legal calendars.

## Local trust model

This is a single-user local decision-support product. By default, both services bind to `127.0.0.1`. Reviewer names are audit attribution, not identity authentication. It is not a multi-user production authorization system. Source records and simulated assumptions remain visibly marked. No patient data is needed.

## Replacement data

Data is a versioned JSON record set, not application code. Replace product, trial, jurisdiction, site, depot, demand, route, rule, event and configuration records together through dataset preview and commit. Regulatory-only research uses the atomic rule import. Both boundaries validate references and provenance before activating records; imports generate proposed plans for review.
