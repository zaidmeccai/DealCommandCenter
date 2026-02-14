"""Salesforce integration - pull open pipeline opportunities."""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from simple_salesforce import Salesforce, SalesforceAuthenticationFailed

logger = logging.getLogger(__name__)

CLOSED_STAGES = {"Closed Won", "Closed Lost"}

OPPORTUNITY_FIELDS = [
    "Id",
    "Name",
    "AccountId",
    "Account.Name",
    "StageName",
    "CloseDate",
    "Amount",
    "LastActivityDate",
    "NextStep",
    "OwnerId",
    "Owner.Email",
    "Description",
    "CreatedDate",
    "LastModifiedDate",
]


@dataclass
class Opportunity:
    id: str
    name: str
    account_name: str
    stage: str
    close_date: date | None
    amount: float
    last_activity_date: date | None
    next_step: str
    description: str
    days_since_last_activity: int | None = None
    account_id: str = ""
    avoma_meetings: list = field(default_factory=list)
    local_context: dict = field(default_factory=dict)

    @property
    def is_at_risk(self) -> bool:
        return self.days_since_last_activity is not None and self.days_since_last_activity >= 5

    @property
    def closes_this_month(self) -> bool:
        if not self.close_date:
            return False
        today = date.today()
        return self.close_date.year == today.year and self.close_date.month == today.month

    @property
    def closes_this_quarter(self) -> bool:
        if not self.close_date:
            return False
        today = date.today()
        q_current = (today.month - 1) // 3
        q_deal = (self.close_date.month - 1) // 3
        return self.close_date.year == today.year and q_deal == q_current


def _parse_date(val: str | None) -> date | None:
    if not val:
        return None
    try:
        return datetime.strptime(val[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


class SalesforceClient:
    """Wrapper around simple-salesforce for pipeline data."""

    def __init__(self, username: str, password: str, security_token: str, domain: str = "login"):
        self.sf: Salesforce | None = None
        self._username = username
        self._password = password
        self._security_token = security_token
        self._domain = domain

    def connect(self) -> bool:
        """Authenticate to Salesforce. Returns True on success."""
        try:
            self.sf = Salesforce(
                username=self._username,
                password=self._password,
                security_token=self._security_token,
                domain=self._domain,
            )
            logger.info("Salesforce: authenticated as %s", self._username)
            return True
        except SalesforceAuthenticationFailed as exc:
            logger.error("Salesforce authentication failed: %s", exc)
            return False
        except Exception as exc:
            logger.error("Salesforce connection error: %s", exc)
            return False

    def get_my_opportunities(self, my_email: str) -> list[Opportunity]:
        """Fetch open opportunities owned by me."""
        if not self.sf:
            logger.error("Salesforce: not connected")
            return []

        fields_str = ", ".join(OPPORTUNITY_FIELDS)
        stage_filter = " AND ".join(f"StageName != '{s}'" for s in CLOSED_STAGES)

        query = (
            f"SELECT {fields_str} FROM Opportunity "
            f"WHERE {stage_filter} "
            f"AND Owner.Email = '{my_email}' "
            f"ORDER BY CloseDate ASC"
        )

        try:
            results = self.sf.query_all(query)
        except Exception as exc:
            logger.error("Salesforce query failed: %s", exc)
            return []

        today = date.today()
        opps: list[Opportunity] = []

        for record in results.get("records", []):
            last_activity = _parse_date(record.get("LastActivityDate"))
            days_since = (today - last_activity).days if last_activity else None

            account = record.get("Account") or {}
            owner = record.get("Owner") or {}

            opp = Opportunity(
                id=record.get("Id", ""),
                name=record.get("Name", ""),
                account_name=account.get("Name", "Unknown Account"),
                stage=record.get("StageName", ""),
                close_date=_parse_date(record.get("CloseDate")),
                amount=float(record.get("Amount") or 0),
                last_activity_date=last_activity,
                next_step=record.get("NextStep") or "",
                description=record.get("Description") or "",
                days_since_last_activity=days_since,
                account_id=record.get("AccountId") or "",
            )
            opps.append(opp)

        logger.info("Salesforce: fetched %d open opportunities", len(opps))
        return opps
