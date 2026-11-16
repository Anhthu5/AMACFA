"""Find shared payment accounts within a single audit using local or Neo4j edges."""

from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from amacfa.config import Settings
from amacfa.models import Evidence, EvidenceBackendError, Rule, Signal

RelationshipSearch = Callable[[str, list[Evidence]], list[Signal]]
PATH = "Vendor <- Invoice -> Account <- Invoice -> Vendor"

# Fixed, parameterized queries. Every entity and traversal is scoped to a case.
UPSERT = """
UNWIND $rows AS row
MERGE (batch:AmacfaBatch {id: $audit_id})
MERGE (invoice:AmacfaInvoice {audit_id: $audit_id, line: row.line})
MERGE (vendor:AmacfaVendor {audit_id: $audit_id, id: row.vendor})
MERGE (account:AmacfaAccount {audit_id: $audit_id, token: row.token})
MERGE (batch)-[:HAS_INVOICE]->(invoice)
MERGE (invoice)-[:ISSUED_BY]->(vendor)
MERGE (invoice)-[:PAYS_TO]->(account)
"""

FIND_SHARED = """
MATCH (:AmacfaBatch {id: $audit_id})-[:HAS_INVOICE]->(invoice:AmacfaInvoice
      {audit_id: $audit_id})-[:PAYS_TO]->(account:AmacfaAccount {audit_id: $audit_id})
MATCH (invoice)-[:ISSUED_BY]->(vendor:AmacfaVendor {audit_id: $audit_id})
WITH account, collect(DISTINCT invoice.line) AS lines, count(DISTINCT vendor) AS vendor_count
WHERE vendor_count > 1
RETURN lines, vendor_count
"""


def _signal(lines: list[int], vendor_count: int) -> Signal:
    return Signal(
        rule=Rule.SHARED_ACCOUNT,
        lines=sorted(lines),
        metrics={"vendor_count": vendor_count, "evidence_path": PATH},
    )


def _local_search(_: str, rows: list[Evidence]) -> list[Signal]:
    by_account: dict[str, list[Evidence]] = defaultdict(list)
    for row in rows:
        if row.invoice.account_token:
            by_account[row.invoice.account_token].append(row)
    signals = []
    for group in by_account.values():
        vendor_count = len({row.invoice.vendor_id for row in group})
        if vendor_count > 1:
            signals.append(_signal([row.line for row in group], vendor_count))
    return signals


@contextmanager
def relationship_search(settings: Settings) -> Iterator[RelationshipSearch]:
    if settings.graph_backend == "local":
        yield _local_search
        return

    from neo4j import GraphDatabase
    from neo4j.exceptions import DriverError, Neo4jError

    assert settings.neo4j_password is not None
    with GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
        connection_timeout=5,
        connection_acquisition_timeout=10,
        max_transaction_retry_time=5,
    ) as driver:
        driver.verify_connectivity()

        def search(audit_id: str, rows: list[Evidence]) -> list[Signal]:
            records = [
                {
                    "line": row.line,
                    "vendor": row.invoice.vendor_id,
                    "token": row.invoice.account_token,
                }
                for row in rows
                if row.invoice.account_token
            ]

            def write_and_read(tx):
                tx.run(UPSERT, audit_id=audit_id, rows=records).consume()
                return [
                    _signal(record["lines"], record["vendor_count"])
                    for record in tx.run(FIND_SHARED, audit_id=audit_id)
                ]

            try:
                with driver.session(database=settings.neo4j_database) as session:
                    return session.execute_write(write_and_read)
            except (Neo4jError, DriverError, OSError) as exc:
                raise EvidenceBackendError("Neo4j traversal failed.") from exc

        yield search
