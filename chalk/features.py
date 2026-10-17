"""Deploy with chalkpy installed in a separate Chalk development environment."""
from chalk.features import features


@features
class Shipment:
    id: str
    ready_date: str
    duration_days_json: str
    holidays_json: str
    target_delivery: str
    constraint_blocked: bool
    synthetic_count: int
    risk_model_json: str
    low_slack_days: int
    baseline_transit_days: float
    disruption_delay_days: float
    customs_buffer_days: float
    effective_transit_days: float
    permit_ready: bool
    label_ready: bool
    projected_delivery_at: str
    slack_days: float
    risk_score: float
    risk_band: str


@features
class CountryPlan:
    id: str
    active_rule_version: str
    permit_lead_days: float
    required_language_count: int
    verification_coverage: float
    unresolved_requirement_count: int
    readiness_score: float


@features
class LabelGroup:
    id: str
    country_count: int
    language_count: int
    estimated_pages: int
    compatible: bool
    rework_days: float
    affected_by_change: bool


@features
class Route:
    id: str
    baseline_transit_days: float
    weather_severity: float
    closure_status: bool
    capacity_risk: float
    disruption_delay_days: float
    effective_transit_days: float


@features
class Scenario:
    id: str
    shipments_at_risk: int
    max_delay_days: float
    labels_requiring_rework: int
    countries_blocked: int
