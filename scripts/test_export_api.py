#!/usr/bin/env python3
"""
Integration test script for the BittyTax Export API.

Usage:
    python scripts/test_export_api.py dev   --api-key <key> --wallet 0xABC... [--wallet 0xDEF...]
    python scripts/test_export_api.py prod  --api-key <key> --basic-auth user:pass --wallet 0xABC...

Arguments:
    env             dev | prod  (selects base URL)
    --api-key       DEFITAXES_EXPORT_API_KEY value
    --basic-auth    HTTP Basic Auth credentials in user:password format (for prod)
    --wallet        Wallet address(es). First is primary. Repeat for multiple.
    --currency      Optional fiat currency (default: USD)
    --macos         Pass is_macos=true in the submit payload (for macOS-formatted XLSX)
    --base-url      Override the base URL entirely
    --poll-interval Seconds between status polls (default: 10)
    --timeout       Max seconds to wait for job completion (default: 1800)
    --output-dir    Directory to save the downloaded XLSX (default: current dir)

Exit codes:
    0   All tests passed
    1   One or more tests failed
"""

import argparse
import os
import sys
import time

import requests

# ── Base URLs per environment ─────────────────────────────────────────────────

BASE_URLS = {
    "dev": "http://localhost:8000",
    "prod": "https://defitaxes.us",
}

SUBMIT_PATH = "/api/export/submit"
STATUS_PATH = "/api/export/status"
RESULT_PATH = "/api/export/result"

# ── Helpers ───────────────────────────────────────────────────────────────────

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[94mINFO\033[0m"

failures = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    if condition:
        print(f"  [{PASS}] {label}")
    else:
        msg = f"  [{FAIL}] {label}" + (f" — {detail}" if detail else "")
        print(msg)
        failures.append(label)
    return condition


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def _wait_for_address_free(
    base: str,
    api_key: str,
    job_id: str,
    address: str,
    poll_interval: int = 5,
    timeout: int = 300,
    basic_auth: tuple = None,
) -> None:
    """Poll the given job until it leaves the processing state (complete or failed),
    so the address is free for the next submit."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = get(
            base,
            api_key,
            STATUS_PATH,
            {"job_id": job_id, "address": address},
            basic_auth=basic_auth,
        )
        if r.status_code != 200:
            break
        if r.json().get("status") != "processing":
            break
        print(f"  [{INFO}] Waiting for address to free up…")
        time.sleep(poll_interval)


def post(
    base: str,
    api_key: str,
    path: str,
    body: dict,
    headers_extra: dict = None,
    basic_auth: tuple = None,
) -> requests.Response:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    if headers_extra:
        headers.update(headers_extra)
    return requests.post(base + path, json=body, headers=headers, auth=basic_auth, timeout=30)


def get(
    base: str,
    api_key: str,
    path: str,
    params: dict,
    headers_extra: dict = None,
    basic_auth: tuple = None,
) -> requests.Response:
    headers = {"Authorization": f"Bearer {api_key}"}
    if headers_extra:
        headers.update(headers_extra)
    return requests.get(base + path, params=params, headers=headers, auth=basic_auth, timeout=30)


# ── Test suites ───────────────────────────────────────────────────────────────


def test_auth(base: str, _api_key: str, primary_wallet: str, basic_auth: tuple = None) -> None:
    section("Auth — missing / wrong key")

    # No Authorization header (still pass Basic Auth so the request reaches the app)
    r = requests.post(
        base + SUBMIT_PATH,
        json={"wallets": [primary_wallet]},
        auth=basic_auth,
        timeout=10,
    )
    check("No auth header → 401", r.status_code == 401, f"got {r.status_code}")

    # Wrong key
    r = requests.post(
        base + SUBMIT_PATH,
        json={"wallets": [primary_wallet]},
        headers={"Authorization": "Bearer wrong-key"},
        auth=basic_auth,
        timeout=10,
    )
    check("Wrong API key → 401", r.status_code == 401, f"got {r.status_code}")

    # Status with no auth
    r = requests.get(
        base + STATUS_PATH,
        params={"job_id": "fake", "address": primary_wallet},
        auth=basic_auth,
        timeout=10,
    )
    check("Status no auth → 401", r.status_code == 401, f"got {r.status_code}")

    # Result with no auth
    r = requests.get(
        base + RESULT_PATH,
        params={"job_id": "fake", "address": primary_wallet},
        auth=basic_auth,
        timeout=10,
    )
    check("Result no auth → 401", r.status_code == 401, f"got {r.status_code}")


def test_submit_validation(
    base: str, api_key: str, valid_wallet: str, basic_auth: tuple = None
) -> None:
    section("Submit — input validation")

    # Missing wallets
    r = post(base, api_key, SUBMIT_PATH, {}, basic_auth=basic_auth)
    check("Missing wallets → 400", r.status_code == 400, r.text)

    # Empty wallets array
    r = post(base, api_key, SUBMIT_PATH, {"wallets": []}, basic_auth=basic_auth)
    check("Empty wallets array → 400", r.status_code == 400, r.text)

    # Invalid address format
    r = post(base, api_key, SUBMIT_PATH, {"wallets": ["not-an-address"]}, basic_auth=basic_auth)
    check("Invalid address format → 400", r.status_code == 400, r.text)

    # Duplicate addresses
    r = post(
        base, api_key, SUBMIT_PATH, {"wallets": [valid_wallet, valid_wallet]}, basic_auth=basic_auth
    )
    check("Duplicate wallets → 400", r.status_code == 400, r.text)

    # Invalid currency
    r = post(
        base,
        api_key,
        SUBMIT_PATH,
        {"wallets": [valid_wallet], "currency": "XYZ"},
        basic_auth=basic_auth,
    )
    check("Invalid currency → 400", r.status_code == 400, r.text)

    # Invalid export_options value
    r = post(
        base,
        api_key,
        SUBMIT_PATH,
        {"wallets": [valid_wallet], "export_options": {"transfer_in_known": 99}},
        basic_auth=basic_auth,
    )
    check("Invalid export_options value → 400", r.status_code == 400, r.text)


def test_status_errors(
    base: str, api_key: str, primary_wallet: str, basic_auth: tuple = None
) -> None:
    section("Status — error paths")

    # Missing params
    r = get(base, api_key, STATUS_PATH, {}, basic_auth=basic_auth)
    check("Missing job_id and address → 400", r.status_code == 400, r.text)

    # Non-existent job
    r = get(
        base,
        api_key,
        STATUS_PATH,
        {"job_id": "00000000-0000-0000-0000-000000000000", "address": primary_wallet},
        basic_auth=basic_auth,
    )
    check("Non-existent job_id → 404", r.status_code == 404, r.text)

    # Wrong address for a real job (obtain a real job_id first)
    r = post(base, api_key, SUBMIT_PATH, {"wallets": [primary_wallet]}, basic_auth=basic_auth)
    if r.status_code == 200 and "job_id" in r.json():
        job_id = r.json()["job_id"]
        wrong = "0x0000000000000000000000000000000000000001"
        r2 = get(
            base, api_key, STATUS_PATH, {"job_id": job_id, "address": wrong}, basic_auth=basic_auth
        )
        check("Wrong address on valid job → 403", r2.status_code == 403, r2.text)
        # Wait for this job to finish so the address is free for subsequent tests
        _wait_for_address_free(base, api_key, job_id, primary_wallet, basic_auth=basic_auth)
    else:
        check("Setup submit for ownership check succeeded", False, r.text)


def test_result_errors(
    base: str, api_key: str, primary_wallet: str, basic_auth: tuple = None
) -> None:
    section("Result — error paths")

    # Non-existent job
    r = get(
        base,
        api_key,
        RESULT_PATH,
        {"job_id": "00000000-0000-0000-0000-000000000000", "address": primary_wallet},
        basic_auth=basic_auth,
    )
    check("Non-existent job_id → 404", r.status_code == 404, r.text)

    # Valid job that is still processing
    # Wait for any prior job on this address to finish before submitting
    r = post(base, api_key, SUBMIT_PATH, {"wallets": [primary_wallet]}, basic_auth=basic_auth)
    if r.status_code == 200 and "job_id" in r.json():
        job_id = r.json()["job_id"]
        # Check result immediately — should be 400 (not complete yet)
        r2 = get(
            base,
            api_key,
            RESULT_PATH,
            {"job_id": job_id, "address": primary_wallet},
            basic_auth=basic_auth,
        )
        check("Result before complete → 400", r2.status_code == 400, r2.text)

        # Wrong address
        wrong = "0x0000000000000000000000000000000000000001"
        r3 = get(
            base, api_key, RESULT_PATH, {"job_id": job_id, "address": wrong}, basic_auth=basic_auth
        )
        check("Wrong address on valid job → 403", r3.status_code == 403, r3.text)
    else:
        check("Setup submit for result error checks succeeded", False, r.text)


def test_happy_path(
    base: str,
    api_key: str,
    wallets: list,
    currency: str,
    export_options: dict,
    poll_interval: int,
    timeout_secs: int,
    output_dir: str,
    is_macos: bool = False,
    basic_auth: tuple = None,
) -> None:
    section(f"Happy path — {len(wallets)} wallet(s), currency={currency}, is_macos={is_macos}")

    primary = wallets[0]

    # ── Submit (retry on 409 — previous job for this address still running) ───
    payload = {
        "wallets": wallets,
        "currency": currency,
        "is_macos": is_macos,
        "export_options": export_options,
    }
    print(f"  [{INFO}] Submitting job…")
    submit_deadline = time.time() + timeout_secs
    while True:
        r = post(base, api_key, SUBMIT_PATH, payload, basic_auth=basic_auth)
        if r.status_code != 409:
            break
        if time.time() >= submit_deadline:
            check("Submit returns 200 (timed out waiting for previous job)", False, r.text)
            return
        print(f"  [{INFO}] 409 — previous job still running, retrying in {poll_interval}s…")
        time.sleep(poll_interval)

    if not check("Submit returns 200", r.status_code == 200, r.text):
        return

    body = r.json()
    if not check("Response contains job_id", "job_id" in body, str(body)):
        return

    job_id = body["job_id"]
    print(f"  [{INFO}] job_id = {job_id}")

    # ── Poll status ───────────────────────────────────────────────────────────
    deadline = time.time() + timeout_secs
    job_status = None
    while time.time() < deadline:
        r = get(
            base,
            api_key,
            STATUS_PATH,
            {"job_id": job_id, "address": primary},
            basic_auth=basic_auth,
        )
        if not check("Status returns 200", r.status_code == 200, r.text):
            return

        body = r.json()
        job_status = body.get("status")
        print(f"  [{INFO}] status = {job_status}")

        if job_status in ("complete", "failed"):
            break

        check("Status is processing while running", job_status == "processing", str(body))
        time.sleep(poll_interval)
    else:
        check(f"Job completed within {timeout_secs}s", False, "timed out")
        return

    if not check("Job completed with status=complete", job_status == "complete", str(body)):
        if job_status == "failed":
            print(f"  [{FAIL}] Error detail: {body.get('error', 'n/a')}")
        return

    # ── Download result ───────────────────────────────────────────────────────
    print(f"  [{INFO}] Downloading XLSX…")
    r = get(
        base, api_key, RESULT_PATH, {"job_id": job_id, "address": primary}, basic_auth=basic_auth
    )
    if not check("Result returns 200", r.status_code == 200, r.text[:200]):
        return

    content_type = r.headers.get("Content-Type", "")
    check(
        "Content-Type is XLSX",
        "spreadsheetml" in content_type,
        f"got {content_type}",
    )

    disposition = r.headers.get("Content-Disposition", "")
    check("Content-Disposition is attachment", "attachment" in disposition, disposition)
    check("Filename contains job_id", job_id in disposition, disposition)

    xlsx_bytes = r.content
    check("XLSX body is non-empty", len(xlsx_bytes) > 0, f"{len(xlsx_bytes)} bytes")

    # Save to disk
    filename = f"BittyTax_Records_{job_id}.xlsx"
    out_path = os.path.join(output_dir, filename)
    with open(out_path, "wb") as f:
        f.write(xlsx_bytes)
    print(f"  [{INFO}] Saved to {out_path}")
    check("XLSX saved to disk", os.path.exists(out_path))

    # ── Re-download (multi-download check) ───────────────────────────────────
    print(f"  [{INFO}] Re-downloading to verify multi-download within TTL…")
    r2 = get(
        base, api_key, RESULT_PATH, {"job_id": job_id, "address": primary}, basic_auth=basic_auth
    )
    check("Second download returns 200", r2.status_code == 200, r2.text[:200])
    check("Second download same size", len(r2.content) == len(xlsx_bytes))


# ── Entry point ───────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="BittyTax Export API integration tests")
    p.add_argument("env", choices=["dev", "prod"], help="Target environment")
    p.add_argument("--api-key", required=True, help="DEFITAXES_EXPORT_API_KEY value")
    p.add_argument(
        "--basic-auth",
        default=None,
        metavar="USER:PASS",
        help="HTTP Basic Auth credentials (e.g. for prod)",
    )
    p.add_argument(
        "--wallet",
        dest="wallets",
        action="append",
        required=True,
        help="Wallet address (repeat for multiple; first is primary)",
    )
    p.add_argument("--currency", default="USD", help="Fiat currency (default: USD)")
    p.add_argument(
        "--macos",
        action="store_true",
        default=False,
        help="Pass is_macos=true in submit payload (for macOS-formatted XLSX)",
    )
    p.add_argument("--base-url", default=None, help="Override base URL")
    p.add_argument(
        "--poll-interval", type=int, default=10, help="Seconds between polls (default: 10)"
    )
    p.add_argument("--timeout", type=int, default=1800, help="Max wait seconds (default: 1800)")
    p.add_argument("--output-dir", default=".", help="Directory to save downloaded XLSX")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    base = args.base_url or BASE_URLS[args.env]

    # Parse optional Basic Auth credentials
    basic_auth = None
    if args.basic_auth:
        if ":" not in args.basic_auth:
            print(f"  [{FAIL}] --basic-auth must be in user:password format")
            sys.exit(1)
        user, password = args.basic_auth.split(":", 1)
        basic_auth = (user, password)

    print(f"\n{'═' * 60}")
    print("  BittyTax Export API — integration tests")
    print(f"  Environment : {args.env}")
    print(f"  Base URL    : {base}")
    print(f"  Basic Auth  : {'yes' if basic_auth else 'no'}")
    print(f"  Primary     : {args.wallets[0]}")
    if len(args.wallets) > 1:
        print(f"  Secondary   : {', '.join(args.wallets[1:])}")
    print(f"  Currency    : {args.currency}")
    print(f"  macOS XLSX  : {args.macos}")
    print(f"{'═' * 60}")

    os.makedirs(args.output_dir, exist_ok=True)

    export_options = {
        "transfer_in_known": 0,
        "transfer_in_unknown": 0,
        "transfer_out_known": 0,
        "transfer_out_unknown": 0,
    }

    test_auth(base, args.api_key, args.wallets[0], basic_auth=basic_auth)
    test_submit_validation(base, args.api_key, args.wallets[0], basic_auth=basic_auth)
    test_status_errors(base, args.api_key, args.wallets[0], basic_auth=basic_auth)
    test_result_errors(base, args.api_key, args.wallets[0], basic_auth=basic_auth)
    test_happy_path(
        base,
        args.api_key,
        args.wallets,
        args.currency,
        export_options,
        args.poll_interval,
        args.timeout,
        args.output_dir,
        is_macos=args.macos,
        basic_auth=basic_auth,
    )

    print(f"\n{'═' * 60}")
    if failures:
        print(f"  [{FAIL}] {len(failures)} test(s) failed:")
        for f in failures:
            print(f"    • {f}")
        print(f"{'═' * 60}\n")
        sys.exit(1)
    else:
        print(f"  [{PASS}] All tests passed")
        print(f"{'═' * 60}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
