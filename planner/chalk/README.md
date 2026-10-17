# Chalk deployment

The application uses standard-library HTTPS requests; no Chalk SDK is needed at runtime. After creating the project at `chalk.ai/hackharvard`, install `requirements.txt`, log in with the Chalk CLI, initialize this directory if the dashboard has not supplied a project file, and run `chalk apply`. The checked-in features and resolvers are ready to deploy without editing application code.

Set `CHALK_CLIENT_ID`, `CHALK_CLIENT_SECRET`, `CHALK_ENVIRONMENT`, and `CHALK_QUERY_SERVER` to your authenticated feature-engine endpoint. `CHALK_API_SERVER` defaults to `https://api.chalk.ai`. A short-lived `CHALK_ACCESS_TOKEN` is also supported. Configure a service token restricted to online querying and the shipment feature namespace. Never put credentials in browser code.

Queries send normalized scheduling primitives (ready date, stage durations, holidays, target, constraint flags, and configured risk weights) to namespaced features. Deployed resolvers calculate delivery, business-day slack, risk score/band, and disruption-adjusted transit. Computed outputs are never sent as query inputs. Every response is checked against the local formula. Missing credentials, provider failures, or a mismatched deployment preserve the local calculation and report the fallback in diagnostics. Each immutable scenario retains point-in-time feature values and query metadata for replay. No live credentials were available for a deployment verification; mocked contract tests cover request shape, parity, and failure behavior.

Official references used: [Online queries](https://docs.chalk.ai/docs/query-online), [OAuth authentication](https://docs.chalk.ai/docs/online-authentication), [Typed features](https://docs.chalk.ai/docs/features).

## Agent Evals

The repository's `evals/gold.json` contains planner, extraction, change-analysis, citation, and abstention cases. Run `python evals/run.py` from the repository root for the credential-free score. In Chalk Agent Evals, upload the same JSON, use `kind` for evaluation slices, reproduce the pass/fail fields as scorers, and attach the current Git commit as run metadata. This makes the hosted evaluation directly comparable to the local regression report.

## Shipment outlook (agent facts)

`shipment_outlook` and `shipment_agent_answer` in `resolvers.py` turn planner inputs (dispatch date, best/likely/worst leg ranges, holidays, gateway airport, customs source) into best/likely/worst delivery dates, likely and safe ship-by dates, worst-case slack, and the one sentence the Photon agent may say about a shipment's timing. The app requests them in the same online query as the schedule features and checks every value against its own calculation before the agent uses it; on any mismatch or outage the agent falls back to the local calculation and says so.

`logistics_formulas.py` is a byte-identical copy of `packages/feature_provider/logistics.py`, so the deployment stays self-contained. After changing the formulas, copy the file again; `tests/unit/test_chalk_outlook.py` fails until the copies match. `python evals/run.py` includes `ship_by_accuracy` cases that ask the agent about every country and require each answer to state the planner's own dates.
