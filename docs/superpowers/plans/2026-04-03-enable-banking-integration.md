# Enable Banking Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automatic Rabobank transaction sync via Enable Banking API alongside the existing CSV import.

**Architecture:** New `import_/enablebanking.py` module handles JWT authentication and API calls. A `bank_connections` database table stores session/consent data. The bank page (`pages/bank.py`) gets a connection management section and sync button. Transactions from the API are mapped to the same dict format as `parse_rabobank_csv()`, then fed into the existing `add_banktransacties()` + `find_factuur_matches()` pipeline.

**Tech Stack:** Python 3.12+, NiceGUI, SQLite (aiosqlite), PyJWT (RS256), requests, Enable Banking REST API

**Prerequisites (manual, before starting):**
1. User must register at https://enablebanking.com/sign-in/
2. Create a sandbox application in the Enable Banking Control Panel
3. Download the generated private key PEM file to `data/enablebanking_key.pem`
4. Note the Application ID (UUID format)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `import_/enablebanking.py` | Enable Banking API client: JWT auth, start authorization, create session, fetch transactions, map to app format |
| Create | `tests/test_enablebanking.py` | Tests for API client and transaction mapping |
| Modify | `database.py` | Migration 24 (bank_connections table) + CRUD functions for connections |
| Modify | `models.py` | `BankConnection` dataclass |
| Modify | `pages/bank.py` | Connection UI section, sync button, callback route |
| Modify | `requirements.txt` | Add `PyJWT[crypto]`, `requests` |
| Modify | `tests/test_database.py` | Tests for bank_connections CRUD |

---

### Task 1: Add Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add PyJWT and cryptography to requirements**

In `requirements.txt`, add after `weasyprint`:
```
PyJWT[crypto]>=2.8
requests>=2.31
```

(`PyJWT[crypto]` installs `cryptography` as a dependency — no need to list it separately. `requests` is needed for the Enable Banking HTTP calls.)

- [ ] **Step 2: Install the new dependencies**

Run:
```bash
source .venv/bin/activate && pip install "PyJWT[crypto]>=2.8" "requests>=2.31"
```

Expected: Successfully installed PyJWT, cryptography, and requests

- [ ] **Step 3: Verify imports work**

Run:
```bash
.venv/bin/python -c "import jwt; import requests; print(jwt.__version__, requests.__version__)"
```

Expected: Version numbers printed (e.g., `2.9.0 2.32.3`)

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "feat: add PyJWT dependency for Enable Banking integration"
```

---

### Task 2: BankConnection Model

**Files:**
- Modify: `models.py:98` (add after `Banktransactie` dataclass)

- [ ] **Step 1: Read current models.py**

Read `models.py` to confirm the exact location and imports.

- [ ] **Step 2: Add BankConnection dataclass**

Add after the `Banktransactie` dataclass in `models.py`:

```python
@dataclass
class BankConnection:
    id: int = 0
    provider: str = ''           # 'enablebanking'
    app_id: str = ''             # Enable Banking Application ID (UUID)
    session_id: str = ''         # Enable Banking session ID
    account_uid: str = ''        # Enable Banking account UID
    account_iban: str = ''       # The connected IBAN
    consent_valid_until: str = ''  # ISO date: YYYY-MM-DD
    last_sync: str = ''          # ISO datetime: YYYY-MM-DD HH:MM:SS
    status: str = ''             # 'active', 'expired', 'disconnected'
```

- [ ] **Step 3: Verify no syntax errors**

Run:
```bash
.venv/bin/python -c "from models import BankConnection; print(BankConnection())"
```

Expected: `BankConnection(id=0, provider='', app_id='', session_id='', account_uid='', account_iban='', consent_valid_until='', last_sync='', status='')`

- [ ] **Step 4: Commit**

```bash
git add models.py
git commit -m "feat: add BankConnection dataclass"
```

---

### Task 3: Database Migration — bank_connections Table

**Files:**
- Modify: `database.py` — migration list (~line 354) + new CRUD functions
- Test: `tests/test_database.py`

- [ ] **Step 1: Write tests for bank_connections CRUD**

Add to `tests/test_database.py`:

```python
import pytest
from database import (
    init_db, get_bank_connection, save_bank_connection,
    delete_bank_connection, DB_PATH,
)
from models import BankConnection


@pytest.mark.asyncio
async def test_save_and_get_bank_connection(tmp_path):
    db = tmp_path / "test.db"
    await init_db(db)
    conn = BankConnection(
        provider='enablebanking',
        app_id='test-app-id',
        session_id='test-session',
        account_uid='test-uid',
        account_iban='NL00RABO0123456789',
        consent_valid_until='2026-10-01',
        last_sync='2026-04-03 12:00:00',
        status='active',
    )
    await save_bank_connection(db, conn)
    result = await get_bank_connection(db)
    assert result is not None
    assert result.provider == 'enablebanking'
    assert result.app_id == 'test-app-id'
    assert result.session_id == 'test-session'
    assert result.account_uid == 'test-uid'
    assert result.account_iban == 'NL00RABO0123456789'
    assert result.consent_valid_until == '2026-10-01'
    assert result.status == 'active'


@pytest.mark.asyncio
async def test_save_bank_connection_upserts(tmp_path):
    db = tmp_path / "test.db"
    await init_db(db)
    conn1 = BankConnection(provider='enablebanking', app_id='id1', status='active')
    await save_bank_connection(db, conn1)
    conn2 = BankConnection(provider='enablebanking', app_id='id2', status='expired')
    await save_bank_connection(db, conn2)
    result = await get_bank_connection(db)
    assert result.app_id == 'id2'
    assert result.status == 'expired'


@pytest.mark.asyncio
async def test_get_bank_connection_returns_none_when_empty(tmp_path):
    db = tmp_path / "test.db"
    await init_db(db)
    result = await get_bank_connection(db)
    assert result is None


@pytest.mark.asyncio
async def test_delete_bank_connection(tmp_path):
    db = tmp_path / "test.db"
    await init_db(db)
    conn = BankConnection(provider='enablebanking', app_id='id1', status='active')
    await save_bank_connection(db, conn)
    await delete_bank_connection(db)
    result = await get_bank_connection(db)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py::test_save_and_get_bank_connection tests/test_database.py::test_save_bank_connection_upserts tests/test_database.py::test_get_bank_connection_returns_none_when_empty tests/test_database.py::test_delete_bank_connection -v
```

Expected: FAIL — `ImportError: cannot import name 'get_bank_connection'`

- [ ] **Step 3: Add migration 24 to database.py**

Find the migrations list (currently ends at migration 23). Add migration 24:

```python
(24, "create_bank_connections", [
    """CREATE TABLE IF NOT EXISTS bank_connections (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        provider TEXT NOT NULL DEFAULT 'enablebanking',
        app_id TEXT NOT NULL DEFAULT '',
        session_id TEXT NOT NULL DEFAULT '',
        account_uid TEXT NOT NULL DEFAULT '',
        account_iban TEXT NOT NULL DEFAULT '',
        consent_valid_until TEXT NOT NULL DEFAULT '',
        last_sync TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT ''
    )""",
]),
```

Note: `CHECK (id = 1)` ensures only one row (same pattern as `bedrijfsgegevens`). This is a single-user app with one bank account.

- [ ] **Step 4: Add CRUD functions to database.py**

Add these functions after the existing bank transaction functions (after `delete_banktransacties`):

```python
async def get_bank_connection(db_path: Path = DB_PATH) -> Optional['BankConnection']:
    """Get the bank connection (single-row table)."""
    from models import BankConnection
    async with get_db_ctx(db_path) as conn:
        row = await conn.execute_fetchall(
            "SELECT id, provider, app_id, session_id, account_uid, "
            "account_iban, consent_valid_until, last_sync, status "
            "FROM bank_connections LIMIT 1"
        )
        if not row:
            return None
        r = row[0]
        return BankConnection(
            id=r[0], provider=r[1], app_id=r[2], session_id=r[3],
            account_uid=r[4], account_iban=r[5], consent_valid_until=r[6],
            last_sync=r[7], status=r[8],
        )


async def save_bank_connection(db_path: Path = DB_PATH,
                                connection: 'BankConnection' = None) -> None:
    """Insert or replace the bank connection (single-row table)."""
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO bank_connections "
            "(id, provider, app_id, session_id, account_uid, "
            "account_iban, consent_valid_until, last_sync, status) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
            (connection.provider, connection.app_id, connection.session_id,
             connection.account_uid, connection.account_iban,
             connection.consent_valid_until, connection.last_sync,
             connection.status),
        )
        await conn.commit()


async def delete_bank_connection(db_path: Path = DB_PATH) -> None:
    """Remove the bank connection."""
    async with get_db_ctx(db_path) as conn:
        await conn.execute("DELETE FROM bank_connections")
        await conn.commit()
```

Also add the import for `Optional` from typing if not already present (check the imports at the top of database.py).

- [ ] **Step 5: Export the new functions**

Check that the new functions are importable. Also add them to any `__all__` list if the file uses one (it likely doesn't — verify).

- [ ] **Step 6: Run tests to verify they pass**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py::test_save_and_get_bank_connection tests/test_database.py::test_save_bank_connection_upserts tests/test_database.py::test_get_bank_connection_returns_none_when_empty tests/test_database.py::test_delete_bank_connection -v
```

Expected: 4 PASSED

- [ ] **Step 7: Run full test suite**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

Expected: All tests pass (no regressions)

- [ ] **Step 8: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: add bank_connections table and CRUD functions"
```

---

### Task 4: Enable Banking API Client — JWT Auth + Transaction Mapping

**Files:**
- Create: `import_/enablebanking.py`
- Create: `tests/test_enablebanking.py`

This task creates the core API client module. It handles:
1. JWT token generation for Enable Banking authentication
2. Starting bank authorization (returns URL for user redirect)
3. Creating a session from the callback code
4. Fetching transactions
5. Mapping Berlin Group transaction format to the app's dict format

- [ ] **Step 1: Write tests for transaction mapping**

Create `tests/test_enablebanking.py`:

```python
import pytest
from import_.enablebanking import map_transactions_to_app_format


class TestMapTransactions:
    """Test mapping from Berlin Group format to app dict format."""

    def test_incoming_payment(self):
        """Incoming payment: debtor fields -> tegenpartij/tegenrekening."""
        api_txn = {
            "transactionId": "txn-001",
            "bookingDate": "2026-04-01",
            "transactionAmount": {"amount": "1500.00", "currency": "EUR"},
            "debtorName": "Huisartsenpraktijk De Laan",
            "debtorAccount": {"iban": "NL91ABNA0417164300"},
            "remittanceInformationUnstructured": "Factuur 2026-001 waarneming maart",
        }
        result = map_transactions_to_app_format([api_txn])
        assert len(result) == 1
        t = result[0]
        assert t["datum"] == "2026-04-01"
        assert t["bedrag"] == 1500.00
        assert t["tegenpartij"] == "Huisartsenpraktijk De Laan"
        assert t["tegenrekening"] == "NL91ABNA0417164300"
        assert t["omschrijving"] == "Factuur 2026-001 waarneming maart"
        assert t["betalingskenmerk"] == ""

    def test_outgoing_payment(self):
        """Outgoing payment: creditor fields -> tegenpartij/tegenrekening."""
        api_txn = {
            "transactionId": "txn-002",
            "bookingDate": "2026-03-15",
            "transactionAmount": {"amount": "-250.00", "currency": "EUR"},
            "creditorName": "Belastingdienst",
            "creditorAccount": {"iban": "NL86INGB0002445588"},
            "remittanceInformationUnstructured": "Voorlopige aanslag 2026",
            "remittanceInformationStructured": "1234567890123456",
        }
        result = map_transactions_to_app_format([api_txn])
        t = result[0]
        assert t["bedrag"] == -250.00
        assert t["tegenpartij"] == "Belastingdienst"
        assert t["tegenrekening"] == "NL86INGB0002445588"
        assert t["betalingskenmerk"] == "1234567890123456"

    def test_missing_optional_fields(self):
        """Transaction with minimal fields."""
        api_txn = {
            "transactionId": "txn-003",
            "bookingDate": "2026-02-01",
            "transactionAmount": {"amount": "-15.50", "currency": "EUR"},
        }
        result = map_transactions_to_app_format([api_txn])
        t = result[0]
        assert t["datum"] == "2026-02-01"
        assert t["bedrag"] == -15.50
        assert t["tegenpartij"] == ""
        assert t["tegenrekening"] == ""
        assert t["omschrijving"] == ""
        assert t["betalingskenmerk"] == ""

    def test_multiple_transactions(self):
        """Multiple transactions are all mapped."""
        txns = [
            {"bookingDate": "2026-01-01", "transactionAmount": {"amount": "100.00", "currency": "EUR"}},
            {"bookingDate": "2026-01-02", "transactionAmount": {"amount": "-50.00", "currency": "EUR"}},
            {"bookingDate": "2026-01-03", "transactionAmount": {"amount": "200.00", "currency": "EUR"}},
        ]
        result = map_transactions_to_app_format(txns)
        assert len(result) == 3
        assert [t["bedrag"] for t in result] == [100.00, -50.00, 200.00]

    def test_structured_remittance_used_as_betalingskenmerk(self):
        """remittanceInformationStructured maps to betalingskenmerk."""
        api_txn = {
            "bookingDate": "2026-04-01",
            "transactionAmount": {"amount": "-500.00", "currency": "EUR"},
            "remittanceInformationStructured": "8000012345678901",
            "remittanceInformationUnstructured": "Betaling VA IB 2026",
        }
        result = map_transactions_to_app_format([api_txn])
        assert result[0]["betalingskenmerk"] == "8000012345678901"
        assert result[0]["omschrijving"] == "Betaling VA IB 2026"

    def test_amount_string_to_float_conversion(self):
        """Amounts come as strings from the API and must be converted to float."""
        api_txn = {
            "bookingDate": "2026-04-01",
            "transactionAmount": {"amount": "2919.50", "currency": "EUR"},
        }
        result = map_transactions_to_app_format([api_txn])
        assert result[0]["bedrag"] == 2919.50
        assert isinstance(result[0]["bedrag"], float)

    def test_empty_list(self):
        """Empty input returns empty output."""
        assert map_transactions_to_app_format([]) == []

    def test_uses_valuedate_when_bookingdate_missing(self):
        """Falls back to valueDate if bookingDate is absent."""
        api_txn = {
            "valueDate": "2026-03-28",
            "transactionAmount": {"amount": "100.00", "currency": "EUR"},
        }
        result = map_transactions_to_app_format([api_txn])
        assert result[0]["datum"] == "2026-03-28"

    def test_skips_transaction_without_any_date(self):
        """Transaction without bookingDate or valueDate is skipped."""
        api_txn = {
            "transactionAmount": {"amount": "100.00", "currency": "EUR"},
        }
        result = map_transactions_to_app_format([api_txn])
        assert len(result) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_enablebanking.py -v
```

Expected: FAIL — `ImportError: cannot import name 'map_transactions_to_app_format'`

- [ ] **Step 3: Create the Enable Banking client module**

Create `import_/enablebanking.py`:

```python
"""Enable Banking API client for Rabobank transaction sync.

Handles JWT authentication, bank authorization flow, session management,
and transaction fetching via the Enable Banking REST API.

Docs: https://enablebanking.com/docs/api/quick-start/
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import jwt as pyjwt
import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.enablebanking.com"
SANDBOX_BASE = "https://api.enablebanking.com"  # Same base, sandbox via app config


def _build_jwt(app_id: str, private_key_path: Path) -> str:
    """Build a signed JWT for Enable Banking API authentication.

    Args:
        app_id: The Enable Banking Application ID (UUID).
        private_key_path: Path to the PEM private key file.

    Returns:
        Signed JWT string valid for 1 hour.
    """
    private_key = private_key_path.read_bytes()
    iat = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "iss": "enablebanking.com",
        "aud": "api.enablebanking.com",
        "iat": iat,
        "exp": iat + 3600,
    }
    return pyjwt.encode(
        payload, private_key, algorithm="RS256",
        headers={"kid": app_id},
    )


def _headers(app_id: str, private_key_path: Path) -> dict:
    """Build authorization headers with a fresh JWT."""
    token = _build_jwt(app_id, private_key_path)
    return {"Authorization": f"Bearer {token}"}


def start_authorization(app_id: str, private_key_path: Path,
                        redirect_url: str,
                        psu_type: str = "personal",
                        valid_days: int = 180) -> dict:
    """Start the bank authorization flow. Returns auth URL for user redirect.

    Args:
        app_id: Enable Banking Application ID.
        private_key_path: Path to PEM key file.
        redirect_url: Where the user returns after bank auth (e.g., http://127.0.0.1:8085/bank-callback).
        psu_type: "personal" or "business".
        valid_days: How long consent should last (max 180 for Rabobank).

    Returns:
        Dict with 'url' (redirect user here) and 'state' (for verification).
    """
    headers = _headers(app_id, private_key_path)
    state = str(uuid.uuid4())
    valid_until = (datetime.now(timezone.utc) + timedelta(days=valid_days)).isoformat()

    body = {
        "access": {"valid_until": valid_until},
        "aspsp": {"name": "Rabobank", "country": "NL"},
        "state": state,
        "redirect_url": redirect_url,
        "psu_type": psu_type,
    }

    r = requests.post(f"{API_BASE}/auth", json=body, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    return {"url": data["url"], "state": state, "valid_until": valid_until}


def create_session(app_id: str, private_key_path: Path,
                   code: str) -> dict:
    """Exchange the callback code for a session with account info.

    Args:
        app_id: Enable Banking Application ID.
        private_key_path: Path to PEM key file.
        code: The authorization code from the callback URL.

    Returns:
        Dict with 'session_id', 'accounts' (list of dicts with 'uid' and 'iban').
    """
    headers = _headers(app_id, private_key_path)
    r = requests.post(f"{API_BASE}/sessions", json={"code": code},
                      headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()

    accounts = []
    for acc in data.get("accounts", []):
        accounts.append({
            "uid": acc.get("uid", acc.get("id", "")),
            "iban": acc.get("iban", acc.get("account_id", {}).get("iban", "")),
        })

    return {
        "session_id": data.get("session_id", ""),
        "accounts": accounts,
    }


def fetch_transactions(app_id: str, private_key_path: Path,
                       account_uid: str,
                       date_from: str = "",
                       date_to: str = "") -> list[dict]:
    """Fetch transactions for a linked account.

    Args:
        app_id: Enable Banking Application ID.
        private_key_path: Path to PEM key file.
        account_uid: The account UID from create_session.
        date_from: ISO date string (YYYY-MM-DD). If empty, API default.
        date_to: ISO date string (YYYY-MM-DD). If empty, today.

    Returns:
        List of raw Berlin Group transaction dicts.
    """
    headers = _headers(app_id, private_key_path)
    params = {}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to

    all_transactions = []
    while True:
        r = requests.get(f"{API_BASE}/accounts/{account_uid}/transactions",
                         params=params, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        all_transactions.extend(data.get("transactions", []))

        continuation_key = data.get("continuation_key")
        if not continuation_key:
            break
        params["continuation_key"] = continuation_key

    return all_transactions


def map_transactions_to_app_format(api_transactions: list[dict]) -> list[dict]:
    """Map Berlin Group transactions to the app's banktransactie dict format.

    Produces dicts with the same keys as parse_rabobank_csv():
    datum, bedrag, tegenrekening, tegenpartij, omschrijving, betalingskenmerk.

    Args:
        api_transactions: Raw transaction dicts from Enable Banking API.

    Returns:
        List of dicts compatible with add_banktransacties().
    """
    result = []
    for txn in api_transactions:
        # Date: prefer bookingDate, fall back to valueDate
        datum = txn.get("bookingDate") or txn.get("valueDate")
        if not datum:
            logger.warning("Skipping transaction without date: %s",
                           txn.get("transactionId", "unknown"))
            continue

        # Amount: string -> float
        amount_str = txn.get("transactionAmount", {}).get("amount", "0")
        bedrag = float(amount_str)

        # Counterparty: for outgoing payments use creditor, for incoming use debtor
        if bedrag < 0:
            tegenpartij = txn.get("creditorName", "")
            tegenrekening = txn.get("creditorAccount", {}).get("iban", "")
        else:
            tegenpartij = txn.get("debtorName", "")
            tegenrekening = txn.get("debtorAccount", {}).get("iban", "")

        # Description
        omschrijving = txn.get("remittanceInformationUnstructured", "")

        # Betalingskenmerk: try structured remittance info first
        betalingskenmerk = txn.get("remittanceInformationStructured", "")

        result.append({
            "datum": datum,
            "bedrag": bedrag,
            "tegenrekening": tegenrekening,
            "tegenpartij": tegenpartij,
            "omschrijving": omschrijving,
            "betalingskenmerk": betalingskenmerk,
        })

    return result


async def sync_transactions(app_id: str, private_key_path: Path,
                            account_uid: str,
                            date_from: str = "") -> list[dict]:
    """Async wrapper: fetch + map transactions. Runs HTTP in a thread.

    Args:
        app_id: Enable Banking Application ID.
        private_key_path: Path to PEM key file.
        account_uid: The account UID.
        date_from: ISO date (YYYY-MM-DD) to fetch from. Defaults to 90 days ago.

    Returns:
        List of app-format transaction dicts ready for add_banktransacties().
    """
    if not date_from:
        date_from = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    raw = await asyncio.to_thread(
        fetch_transactions, app_id, private_key_path, account_uid, date_from
    )
    return map_transactions_to_app_format(raw)
```

- [ ] **Step 4: Run mapping tests to verify they pass**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_enablebanking.py -v
```

Expected: 10 PASSED

- [ ] **Step 5: Write tests for JWT generation**

Add to `tests/test_enablebanking.py`:

```python
from pathlib import Path
from unittest.mock import patch, MagicMock
from import_.enablebanking import _build_jwt, _headers


class TestJWTAuth:
    """Test JWT token generation."""

    def test_build_jwt_creates_valid_token(self, tmp_path):
        """JWT contains correct claims and is RS256-signed."""
        # Generate a test RSA key
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_path = tmp_path / "test_key.pem"
        key_path.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))

        app_id = "test-app-123"
        token = _build_jwt(app_id, key_path)

        # Decode without verification to check claims
        claims = pyjwt.decode(token, options={"verify_signature": False})
        assert claims["iss"] == "enablebanking.com"
        assert claims["aud"] == "api.enablebanking.com"
        assert "iat" in claims
        assert "exp" in claims
        assert claims["exp"] - claims["iat"] == 3600

        # Check kid header
        header = pyjwt.get_unverified_header(token)
        assert header["kid"] == "test-app-123"
        assert header["alg"] == "RS256"

    def test_headers_returns_bearer_token(self, tmp_path):
        """_headers returns dict with Authorization: Bearer <jwt>."""
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_path = tmp_path / "test_key.pem"
        key_path.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))

        headers = _headers("app-id", key_path)
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")
```

Also add the import at the top of the test file:
```python
import jwt as pyjwt
```

- [ ] **Step 6: Run all enablebanking tests**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_enablebanking.py -v
```

Expected: 12 PASSED

- [ ] **Step 7: Run full test suite to check for regressions**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add import_/enablebanking.py tests/test_enablebanking.py
git commit -m "feat: add Enable Banking API client with JWT auth and transaction mapping"
```

---

### Task 5: Bank Page UI — Connection Management Section

**Files:**
- Modify: `pages/bank.py` — add connection UI section between header and filter toolbar

This task adds the UI for:
1. Displaying connection status (connected/disconnected/expired)
2. "Koppel Rabobank" button to start authorization
3. "Sync transacties" button to fetch new transactions
4. "Ontkoppel" button to remove the connection
5. App ID configuration input (first-time setup)

- [ ] **Step 1: Read current pages/bank.py**

Read the full file to understand the current layout structure and identify the exact insertion point.

- [ ] **Step 2: Add Enable Banking imports to bank.py**

Add these imports at the top of `pages/bank.py` (after the existing imports):

```python
from import_.enablebanking import start_authorization, sync_transactions
from database import get_bank_connection, save_bank_connection, delete_bank_connection
from models import BankConnection
```

- [ ] **Step 3: Add connection state and helper functions**

After the existing state dicts (around line 31), add:

```python
    bank_conn_ref = {'ref': None}  # container for connection status UI

    async def refresh_connection_status():
        """Refresh the bank connection status UI section."""
        container = bank_conn_ref.get('ref')
        if not container:
            return
        container.clear()
        conn = await get_bank_connection(DB_PATH)
        with container:
            if conn and conn.status == 'active':
                # Check if consent is about to expire
                days_left = ''
                if conn.consent_valid_until:
                    try:
                        expiry = datetime.strptime(conn.consent_valid_until[:10], '%Y-%m-%d')
                        days_left_num = (expiry - datetime.now()).days
                        if days_left_num < 0:
                            days_left = ' (verlopen!)'
                            conn.status = 'expired'
                            await save_bank_connection(DB_PATH, conn)
                        elif days_left_num <= 14:
                            days_left = f' (verloopt over {days_left_num} dagen)'
                    except ValueError:
                        pass

                with ui.row().classes('items-center gap-4'):
                    ui.icon('link').classes('text-positive text-xl')
                    ui.label(f'Gekoppeld: {conn.account_iban}').classes('text-body1')
                    if conn.last_sync:
                        ui.label(f'Laatste sync: {conn.last_sync}').classes('text-caption text-grey')
                    if days_left:
                        color = 'text-negative' if 'verlopen' in days_left else 'text-warning'
                        ui.label(f'Consent{days_left}').classes(f'text-caption {color}')

                with ui.row().classes('gap-2'):
                    if conn.status == 'expired':
                        ui.button('Vernieuw koppeling', on_click=on_start_auth,
                                  icon='refresh').props('color=warning')
                    else:
                        ui.button('Sync transacties', on_click=on_sync,
                                  icon='sync').props('color=primary')
                    ui.button('Ontkoppel', on_click=on_disconnect,
                              icon='link_off').props('flat color=negative')

            elif conn and conn.status == 'expired':
                with ui.row().classes('items-center gap-4'):
                    ui.icon('link_off').classes('text-warning text-xl')
                    ui.label('Koppeling verlopen — vernieuw de autorisatie').classes('text-body1')
                ui.button('Vernieuw koppeling', on_click=on_start_auth,
                          icon='refresh').props('color=warning')

            else:
                # Not connected — show setup
                with ui.row().classes('items-center gap-4'):
                    ui.icon('link_off').classes('text-grey text-xl')
                    ui.label('Geen bankkoppeling actief').classes('text-body1 text-grey')
                ui.button('Koppel Rabobank', on_click=on_start_auth,
                          icon='account_balance').props('color=primary')
```

- [ ] **Step 4: Add the authorization start handler**

Add below the connection status helper:

```python
    async def on_start_auth():
        """Start the Enable Banking authorization flow."""
        conn = await get_bank_connection(DB_PATH)
        key_path = DB_PATH.parent / 'enablebanking_key.pem'

        if not key_path.exists():
            ui.notify('Private key niet gevonden: data/enablebanking_key.pem',
                      type='negative')
            return

        # If no app_id configured yet, ask for it
        if not conn or not conn.app_id:
            with ui.dialog() as dlg, ui.card().classes('w-96'):
                ui.label('Enable Banking instellen').classes('text-h6')
                ui.label('Voer je Application ID in (te vinden in het Enable Banking Control Panel).')
                app_id_input = ui.input('Application ID',
                                        placeholder='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
                                        ).classes('w-full')
                psu_select = ui.select(['personal', 'business'],
                                       value='personal',
                                       label='Rekeningtype').classes('w-full')

                async def do_connect():
                    app_id = app_id_input.value.strip()
                    if not app_id:
                        ui.notify('Application ID is verplicht', type='warning')
                        return
                    new_conn = BankConnection(
                        provider='enablebanking',
                        app_id=app_id,
                        status='connecting',
                    )
                    await save_bank_connection(DB_PATH, new_conn)
                    dlg.close()
                    await _do_start_auth(app_id, key_path, psu_select.value)

                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren', on_click=dlg.close).props('flat')
                    ui.button('Verbinden', on_click=do_connect).props('color=primary')
            dlg.open()
        else:
            await _do_start_auth(conn.app_id, key_path)

    async def _do_start_auth(app_id: str, key_path: Path, psu_type: str = 'personal'):
        """Execute the authorization redirect."""
        try:
            result = await asyncio.to_thread(
                start_authorization,
                app_id, key_path,
                redirect_url='http://127.0.0.1:8085/bank-callback',
                psu_type=psu_type,
            )
            # Store the state for verification on callback
            conn = await get_bank_connection(DB_PATH) or BankConnection()
            conn.provider = 'enablebanking'
            conn.app_id = app_id
            conn.consent_valid_until = result['valid_until'][:10]
            conn.status = 'connecting'
            await save_bank_connection(DB_PATH, conn)

            # Open the auth URL in a new browser tab
            ui.navigate.to(result['url'], new_tab=True)
            ui.notify('Autoriseer in het geopende tabblad via de Rabo Bankieren app. '
                      'Keer daarna hier terug.', type='info', timeout=10000)

        except Exception as exc:
            logger.exception("Enable Banking auth start failed")
            ui.notify(f'Fout bij starten autorisatie: {exc}', type='negative')
```

- [ ] **Step 5: Add the sync handler**

```python
    async def on_sync():
        """Sync transactions from Enable Banking."""
        conn = await get_bank_connection(DB_PATH)
        if not conn or conn.status != 'active':
            ui.notify('Geen actieve bankkoppeling', type='warning')
            return

        key_path = DB_PATH.parent / 'enablebanking_key.pem'
        if not key_path.exists():
            ui.notify('Private key niet gevonden', type='negative')
            return

        # Determine date_from: day after last sync, or 90 days ago
        date_from = ''
        if conn.last_sync:
            try:
                last = datetime.strptime(conn.last_sync[:10], '%Y-%m-%d')
                date_from = (last - timedelta(days=1)).strftime('%Y-%m-%d')
            except ValueError:
                pass

        ui.notify('Transacties ophalen...', type='info')

        try:
            transacties = await sync_transactions(
                conn.app_id, key_path, conn.account_uid, date_from
            )

            if not transacties:
                ui.notify('Geen nieuwe transacties gevonden', type='info')
            else:
                sync_label = datetime.now().strftime('api_sync_%Y%m%d_%H%M%S')
                count = await add_banktransacties(DB_PATH, transacties,
                                                  csv_bestand=sync_label)
                ui.notify(f'{count} nieuwe transacties geimporteerd', type='positive')

                # Auto-match invoices (same as CSV import)
                matches = await find_factuur_matches(DB_PATH)
                if matches:
                    matched = await apply_factuur_matches(DB_PATH, matches)
                    nummers = [m['factuur_nummer'] for m in matches[:matched]]
                    ui.notify(f'{matched} facturen automatisch gekoppeld: {", ".join(nummers)}',
                              type='positive')

            # Update last_sync timestamp
            conn.last_sync = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            await save_bank_connection(DB_PATH, conn)

            await refresh_table()
            await refresh_connection_status()

        except requests.exceptions.HTTPError as exc:
            if exc.response and exc.response.status_code == 429:
                ui.notify('Rate limit bereikt (max 4x per dag). Probeer later opnieuw.',
                          type='warning')
            elif exc.response and exc.response.status_code == 401:
                conn.status = 'expired'
                await save_bank_connection(DB_PATH, conn)
                await refresh_connection_status()
                ui.notify('Autorisatie verlopen. Vernieuw de koppeling.', type='negative')
            else:
                ui.notify(f'API fout: {exc}', type='negative')
        except Exception as exc:
            logger.exception("Enable Banking sync failed")
            ui.notify(f'Sync mislukt: {exc}', type='negative')
```

- [ ] **Step 6: Add the disconnect handler**

```python
    async def on_disconnect():
        """Remove the bank connection."""
        with ui.dialog() as dlg, ui.card():
            ui.label('Bankkoppeling verwijderen?').classes('text-h6')
            ui.label('De koppeling met Rabobank wordt verwijderd. '
                     'Bestaande transacties blijven bewaard. '
                     'Je kunt later opnieuw koppelen.')

            async def do_disconnect():
                await delete_bank_connection(DB_PATH)
                dlg.close()
                await refresh_connection_status()
                ui.notify('Bankkoppeling verwijderd', type='info')

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Annuleren', on_click=dlg.close).props('flat')
                ui.button('Verwijderen', on_click=do_disconnect).props('color=negative')
        dlg.open()
```

- [ ] **Step 7: Add the connection status card to the page layout**

In the page layout section (after the header row with page_title + upload button, before the filter toolbar), add:

```python
        # --- Bank connection status ---
        with ui.card().classes('w-full'):
            ui.label('Bankkoppeling').classes('text-subtitle1 text-weight-medium')
            with ui.column().classes('w-full gap-2') as conn_container:
                bank_conn_ref['ref'] = conn_container
```

Then at the bottom of the page function (after the CSV files section), add the initial load:

```python
    await refresh_connection_status()
```

- [ ] **Step 8: Add the `import asyncio` if not already present**

Check the imports at the top of `pages/bank.py`. Add `import asyncio` if missing (needed for `asyncio.to_thread`). Also add:

```python
from pathlib import Path
import logging
logger = logging.getLogger(__name__)
```

And add `import requests` for the exception type in the sync handler.

- [ ] **Step 9: Run the app manually to verify UI renders**

Run:
```bash
source .venv/bin/activate && export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib && python main.py
```

Open http://127.0.0.1:8085/bank and verify:
- The "Bankkoppeling" card appears
- Shows "Geen bankkoppeling actief" with "Koppel Rabobank" button
- No console errors
- Existing CSV import still works

- [ ] **Step 10: Run full test suite**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 11: Commit**

```bash
git add pages/bank.py
git commit -m "feat: add bank connection management UI on bank page"
```

---

### Task 6: OAuth Callback Route

**Files:**
- Modify: `pages/bank.py` — add new `@ui.page('/bank-callback')` route

The callback route handles the redirect from Enable Banking after the user authorizes with Rabobank. It receives the `code` parameter, creates a session, stores the account info, and redirects back to `/bank`.

- [ ] **Step 1: Add the callback page route**

Add at module level in `pages/bank.py` (outside the `bank_page` function, at the end of the file):

```python
@ui.page('/bank-callback')
async def bank_callback_page(code: str = '', state: str = '', error: str = ''):
    """Handle Enable Banking OAuth callback after Rabobank authorization."""
    from import_.enablebanking import create_session
    from database import get_bank_connection, save_bank_connection, DB_PATH
    from models import BankConnection

    create_layout('Bank', '/bank')

    with ui.column().classes('w-full p-6 max-w-3xl mx-auto gap-4 items-center'):
        if error:
            ui.icon('error').classes('text-negative text-6xl')
            ui.label('Autorisatie mislukt').classes('text-h5')
            ui.label(f'Fout: {error}').classes('text-body1 text-negative')
            ui.button('Terug naar bank', on_click=lambda: ui.navigate.to('/bank'),
                      icon='arrow_back').props('color=primary')
            return

        if not code:
            ui.icon('error').classes('text-negative text-6xl')
            ui.label('Geen autorisatiecode ontvangen').classes('text-h5')
            ui.button('Terug naar bank', on_click=lambda: ui.navigate.to('/bank'),
                      icon='arrow_back').props('color=primary')
            return

        # Show loading state
        spinner = ui.spinner('dots', size='xl')
        status_label = ui.label('Koppeling voltooien...').classes('text-body1')

        try:
            conn = await get_bank_connection(DB_PATH)
            if not conn or not conn.app_id:
                raise ValueError("Geen bank connection configuratie gevonden")

            key_path = DB_PATH.parent / 'enablebanking_key.pem'
            session = await asyncio.to_thread(
                create_session, conn.app_id, key_path, code
            )

            if not session.get('accounts'):
                raise ValueError("Geen rekeningen gevonden in de autorisatie")

            # Use the first account (single-user app)
            account = session['accounts'][0]

            conn.session_id = session['session_id']
            conn.account_uid = account['uid']
            conn.account_iban = account.get('iban', '')
            conn.status = 'active'
            await save_bank_connection(DB_PATH, conn)

            spinner.delete()
            status_label.delete()

            ui.icon('check_circle').classes('text-positive text-6xl')
            ui.label('Rabobank gekoppeld!').classes('text-h5')
            if conn.account_iban:
                ui.label(f'Rekening: {conn.account_iban}').classes('text-body1')
            ui.label('Je kunt nu transacties synchroniseren op de bankpagina.').classes('text-body1')
            ui.button('Ga naar bank', on_click=lambda: ui.navigate.to('/bank'),
                      icon='arrow_forward').props('color=primary')

        except Exception as exc:
            spinner.delete()
            status_label.delete()
            logging.getLogger(__name__).exception("Bank callback failed")

            ui.icon('error').classes('text-negative text-6xl')
            ui.label('Koppeling mislukt').classes('text-h5')
            ui.label(f'Fout: {exc}').classes('text-body1 text-negative')
            ui.button('Terug naar bank', on_click=lambda: ui.navigate.to('/bank'),
                      icon='arrow_back').props('color=primary')
```

- [ ] **Step 2: Add missing imports at module level if needed**

Ensure `import asyncio` and `import logging` are at the top of the file (should already be there from Task 5).

- [ ] **Step 3: Run the app and test the callback route manually**

Run the app and navigate to `http://127.0.0.1:8085/bank-callback` (no params). Verify:
- Shows "Geen autorisatiecode ontvangen" error page
- "Terug naar bank" button works

Navigate to `http://127.0.0.1:8085/bank-callback?error=access_denied`. Verify:
- Shows "Autorisatie mislukt" with the error message

- [ ] **Step 4: Run full test suite**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add pages/bank.py
git commit -m "feat: add OAuth callback route for Enable Banking authorization"
```

---

### Task 7: Integration Test — End-to-End Sync Flow

**Files:**
- Modify: `tests/test_enablebanking.py` — add integration test with mocked API

- [ ] **Step 1: Write integration test for the sync flow**

Add to `tests/test_enablebanking.py`:

```python
@pytest.mark.asyncio
async def test_sync_and_import_flow(tmp_path):
    """End-to-end: API transactions → map → add_banktransacties → dedup."""
    from database import init_db, add_banktransacties, get_banktransacties
    from import_.enablebanking import map_transactions_to_app_format

    db = tmp_path / "test.db"
    await init_db(db)

    # Simulate API response with 3 transactions
    api_transactions = [
        {
            "transactionId": "t1",
            "bookingDate": "2026-04-01",
            "transactionAmount": {"amount": "1500.00", "currency": "EUR"},
            "debtorName": "Huisartsenpraktijk De Laan",
            "debtorAccount": {"iban": "NL91ABNA0417164300"},
            "remittanceInformationUnstructured": "Factuur 2026-001",
        },
        {
            "transactionId": "t2",
            "bookingDate": "2026-04-02",
            "transactionAmount": {"amount": "-250.00", "currency": "EUR"},
            "creditorName": "Belastingdienst",
            "creditorAccount": {"iban": "NL86INGB0002445588"},
            "remittanceInformationUnstructured": "VA IB 2026",
            "remittanceInformationStructured": "8000012345678901",
        },
        {
            "transactionId": "t3",
            "bookingDate": "2026-04-03",
            "transactionAmount": {"amount": "-15.50", "currency": "EUR"},
            "creditorName": "KPN",
        },
    ]

    # Map and import
    mapped = map_transactions_to_app_format(api_transactions)
    assert len(mapped) == 3

    count = await add_banktransacties(db, mapped, csv_bestand='api_sync_20260403')
    assert count == 3

    # Verify in database
    rows = await get_banktransacties(db, jaar=2026)
    assert len(rows) == 3

    # Check field mapping
    t1 = next(r for r in rows if r.tegenpartij == 'Huisartsenpraktijk De Laan')
    assert t1.bedrag == 1500.00
    assert t1.tegenrekening == 'NL91ABNA0417164300'
    assert t1.omschrijving == 'Factuur 2026-001'

    t2 = next(r for r in rows if r.tegenpartij == 'Belastingdienst')
    assert t2.bedrag == -250.00
    assert t2.betalingskenmerk == '8000012345678901'

    # Dedup: importing the same transactions again should add 0
    count2 = await add_banktransacties(db, mapped, csv_bestand='api_sync_20260404')
    assert count2 == 0

    rows_after = await get_banktransacties(db, jaar=2026)
    assert len(rows_after) == 3
```

- [ ] **Step 2: Run the integration test**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_enablebanking.py::test_sync_and_import_flow -v
```

Expected: PASSED

- [ ] **Step 3: Run full test suite**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_enablebanking.py
git commit -m "test: add integration test for Enable Banking sync flow"
```

---

### Task 8: Final Verification & Manual Testing Checklist

- [ ] **Step 1: Run complete test suite one final time**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

Expected: All tests pass, 0 failures

- [ ] **Step 2: Start the app and verify all UI flows**

Run the app and check:

1. `/bank` page loads without errors
2. "Bankkoppeling" card shows "Geen bankkoppeling actief"
3. Clicking "Koppel Rabobank" opens the setup dialog
4. Dialog asks for Application ID and account type
5. Without `data/enablebanking_key.pem`, shows appropriate error
6. Existing CSV import still works normally
7. Filter toolbar, search, category changes all work
8. `/bank-callback` without params shows error page
9. `/bank-callback?error=test` shows error with message

- [ ] **Step 3: Verify no stray imports or unused code**

Grep for any unused imports in modified files:
```bash
.venv/bin/python -m py_compile pages/bank.py && echo "OK"
.venv/bin/python -m py_compile import_/enablebanking.py && echo "OK"
.venv/bin/python -m py_compile database.py && echo "OK"
.venv/bin/python -m py_compile models.py && echo "OK"
```

Expected: All print "OK"

- [ ] **Step 4: Final commit if any cleanup was needed**

```bash
git add -A
git commit -m "chore: cleanup after Enable Banking integration"
```

---

## Post-Implementation: Sandbox Testing Guide

After the code is deployed, the user needs to:

1. **Sign up** at https://enablebanking.com/sign-in/
2. **Create sandbox app** in Control Panel → note Application ID
3. **Download PEM key** → save to `data/enablebanking_key.pem`
4. **Start the app** → go to `/bank` → click "Koppel Rabobank"
5. **Enter Application ID** → select "personal" or "business"
6. **Authorize** via Rabobank sandbox flow
7. **Verify callback** lands on `/bank-callback` and shows success
8. **Click "Sync transacties"** → verify sandbox transactions appear in the table

If sandbox testing succeeds:

9. **Activate production** via Enable Banking Control Panel → Link own account
10. **Re-authorize** with real Rabobank account (Rabo Bankieren app QR scan)
11. **Sync** and verify real transactions match CSV imports
12. **Compare** `betalingskenmerk` field — if not populated via API, note this as a known limitation

---

## Notes for the Implementing Agent

- **Pattern**: The app uses `async with get_db_ctx(db_path) as conn:` for all DB access. Follow this pattern exactly.
- **Blocking I/O**: All `requests` HTTP calls must be wrapped in `asyncio.to_thread()` in any async context. The `sync_transactions()` function already does this.
- **Error notification**: Use `ui.notify('message', type='positive|negative|warning|info')` — never raw JavaScript alerts.
- **Dialog pattern**: `with ui.dialog() as dlg, ui.card():` followed by `dlg.open()`. See existing dialogs in `pages/bank.py` for the exact style.
- **Navigation**: Use `ui.navigate.to(url)` for same-tab, `ui.navigate.to(url, new_tab=True)` for new tab.
- **Test DB**: All database tests use `tmp_path / "test.db"` with `await init_db(db)` to create a fresh database.
- **The `csv_bestand` field**: For API-synced transactions, use a label like `api_sync_YYYYMMDD_HHMMSS` to distinguish from CSV imports. The existing dedup logic uses `(datum, bedrag, tegenpartij, omschrijving)` — not `csv_bestand` — so API and CSV imports won't create duplicates.
