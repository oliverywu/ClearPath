# Chalk deployment

The application uses standard-library HTTPS requests; no Chalk SDK is needed for the offline demo. In a separate environment install `chalkpy`, initialize a Chalk project in this directory, then deploy `features.py` and `resolvers.py` with `chalk apply`.

Set `CHALK_CLIENT_ID`, `CHALK_CLIENT_SECRET`, `CHALK_ENVIRONMENT`, and `CHALK_QUERY_SERVER` to your authenticated feature-engine endpoint. `CHALK_API_SERVER` defaults to `https://api.chalk.ai`. A short-lived `CHALK_ACCESS_TOKEN` is also supported. Configure a service token restricted to online querying and the shipment feature namespace. Never put credentials in browser code.

Queries send normalized scheduling primitives (ready date, stage durations, holidays, target, constraint flags, and configured risk weights) to namespaced features. Deployed resolvers calculate delivery, business-day slack, risk score/band, and disruption-adjusted transit. Computed outputs are never sent as query inputs. Every response is checked against the local formula. Missing credentials, provider failures, or a mismatched deployment preserve the local calculation and report the fallback in diagnostics. Each immutable scenario retains point-in-time feature values and query metadata for replay. No live credentials were available for a deployment verification; mocked contract tests cover request shape, parity, and failure behavior.

Official references used: [Online queries](https://docs.chalk.ai/docs/query-online), [OAuth authentication](https://docs.chalk.ai/docs/online-authentication), [Typed features](https://docs.chalk.ai/docs/features).
