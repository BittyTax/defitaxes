import io
import json
import os
import threading
import traceback
import uuid
from contextlib import redirect_stderr

from bittytax.config import config as bt_config
from bittytax.conv.datafile import DataFile
from bittytax.conv.output_excel import OutputExcel
from bittytax.conv.parsers.defitaxes import DtConfig, DtTransferMapping, defitaxes_parser
from flask import Blueprint, current_app, request, send_file

from ..constants import USER_DIRNAME
from ..fiat_rates import Twelve
from ..redis_wrap import Redis
from ..user import User
from ..util import is_ethereum, is_solana, log, log_error, normalize_address
from .main import _do_process

export_job = Blueprint("export_job", __name__)

# ── Tunable constants ─────────────────────────────────────────────────────────

MAX_WALLETS = 100
JOB_RESULT_TTL_SECONDS = 86400  # 24 hours

# ── Auth helper ───────────────────────────────────────────────────────────────


def _check_api_key():
    """Return a 401 response tuple if the request Bearer token is invalid, else None."""
    expected = current_app.config.get("EXPORT_API_KEY", "")
    if not expected:
        # Key not configured — fail closed rather than open
        return json.dumps({"error": "Export API is not configured"}), 401
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[len("Bearer ") :] != expected:
        return json.dumps({"error": "Invalid or missing API key"}), 401
    return None


# ── Redis helpers ─────────────────────────────────────────────────────────────


def _job_key(job_id: str, field: str) -> str:
    redis_prefix = current_app.config["REDIS_PREFIX"]
    return f"{redis_prefix}:job:{job_id}:{field}"


def _set_job_text(job_id: str, field: str, value: str) -> None:
    current_app.extensions["redis"].setex(_job_key(job_id, field), JOB_RESULT_TTL_SECONDS, value)


def _get_job_text(job_id: str, field: str):
    return current_app.extensions["redis"].get(_job_key(job_id, field))


# ── Address validation ────────────────────────────────────────────────────────


def _is_valid_address(addr: str) -> bool:
    return is_ethereum(addr) or is_solana(addr)


# ── Background worker ─────────────────────────────────────────────────────────


def _run_export_job(job_id, primary, all_wallets, currency, dt_config, is_macos, app_context):
    app_context.push()

    # Redis instance for queue / progress management (mirrors existing /process pattern)
    process_redis = Redis(primary)

    try:
        # Run the full processing pipeline with all submitted wallets.
        # _do_process pushes its own app context internally; passing a fresh one
        # ensures sub-threads it spawns can also push an independent context.
        _do_process(primary, all_wallets, None, process_redis, current_app.app_context())

        # Detect silent processing failures: _do_process never raises; it writes
        # an "error" key to data_cache.json when something goes wrong internally.
        cache_path = os.path.join(
            current_app.instance_path, USER_DIRNAME, primary, "data_cache.json"
        )
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if "error" in cache:
            raise RuntimeError(cache["error"])

        # ── BittyTax XLSX generation ──────────────────────────────────────────
        bt_config.ccy = currency

        user = User(primary)
        try:
            rows = user.get_csv_data()
        finally:
            # Always release the SQLite connection so no lock is held during
            # any subsequent processing or error handling.
            user.done()

        def row_to_strings(row):
            return ["" if v is None else (v if isinstance(v, str) else str(v)) for v in row]

        data_file = DataFile(defitaxes_parser, [row_to_strings(row) for row in rows])

        stderr_capture = io.StringIO()
        with redirect_stderr(stderr_capture):
            data_file.parse(dt_config=dt_config)

        bi = io.BytesIO()
        output_excel = OutputExcel("BittyTax", [data_file], is_macos=is_macos, stream=bi)
        output_excel.write_excel()

        redis_binary = current_app.extensions["redis_binary"]
        redis_prefix = current_app.config["REDIS_PREFIX"]
        redis_binary.setex(
            f"{redis_prefix}:job:{job_id}:excel",
            JOB_RESULT_TTL_SECONDS,
            bi.getvalue(),
        )

        _set_job_text(job_id, "status", "complete")
        log("export job complete", job_id, primary)

    except Exception:
        tb = traceback.format_exc()
        log("EXCEPTION in export job", job_id, primary, tb)
        log_error("EXCEPTION in export job", primary, job_id)
        try:
            _set_job_text(job_id, "error", tb)
            _set_job_text(job_id, "status", "failed")
        except Exception:
            pass  # Redis unavailable; nothing more we can do


# ── Endpoints ─────────────────────────────────────────────────────────────────


@export_job.route("/api/export/submit", methods=["POST"])
def submit():
    """
    Submit a BittyTax export job.

    Headers: Authorization: Bearer <DEFITAXES_EXPORT_API_KEY>

    Request body (JSON):
    {
        "wallets": ["0xPrimary...", "0xSecondary..."],   // first entry is primary
        "currency": "USD",                               // optional, default USD
        "export_options": {                              // optional, all default 0
            "transfer_in_known":    0,                   // 0=deposit  1=buy
            "transfer_in_unknown":  0,
            "transfer_out_known":   0,                   // 0=withdrawal 1=sell
            "transfer_out_unknown": 0
        }
    }

    Response 200: { "job_id": "<uuid>" }
    Response 400: { "error": "<reason>" }
    Response 401: { "error": "Invalid or missing API key" }
    """
    denied = _check_api_key()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}

    # ── Wallet validation ─────────────────────────────────────────────────────
    wallets_raw = data.get("wallets")
    if not wallets_raw or not isinstance(wallets_raw, list) or len(wallets_raw) == 0:
        return json.dumps({"error": "wallets must be a non-empty array"}), 400

    if len(wallets_raw) > MAX_WALLETS:
        return (
            json.dumps({"error": f"wallets must not exceed {MAX_WALLETS} addresses"}),
            400,
        )

    wallets = []
    for raw in wallets_raw:
        if not isinstance(raw, str) or not raw.strip():
            return json.dumps({"error": f"Invalid wallet value: {raw!r}"}), 400
        addr = normalize_address(raw.strip())
        if not _is_valid_address(addr):
            return (
                json.dumps({"error": f"Invalid wallet address format: {raw!r}"}),
                400,
            )
        wallets.append(addr)

    if len(wallets) != len(set(wallets)):
        return json.dumps({"error": "Duplicate wallet addresses are not allowed"}), 400

    # ── Currency validation ───────────────────────────────────────────────────
    currency = data.get("currency", "USD")
    if currency not in Twelve.FIAT_SYMBOLS:
        valid = list(Twelve.FIAT_SYMBOLS.keys())
        return (
            json.dumps({"error": f"Unsupported currency {currency!r}. Valid: {valid}"}),
            400,
        )

    # ── Export options validation ─────────────────────────────────────────────
    opts = data.get("export_options") or {}
    try:
        ti_known = int(opts.get("transfer_in_known", 0))
        ti_unknown = int(opts.get("transfer_in_unknown", 0))
        to_known = int(opts.get("transfer_out_known", 0))
        to_unknown = int(opts.get("transfer_out_unknown", 0))
        if not all(v in (0, 1) for v in (ti_known, ti_unknown, to_known, to_unknown)):
            raise ValueError("values must be 0 or 1")
    except (ValueError, TypeError) as exc:
        return json.dumps({"error": f"Invalid export_options: {exc}"}), 400

    dt_config = DtConfig(
        transfer_in_known=DtTransferMapping(ti_known),
        transfer_in_unknown=DtTransferMapping(ti_unknown),
        transfer_out_known=DtTransferMapping(to_known),
        transfer_out_unknown=DtTransferMapping(to_unknown),
    )

    # ── is_macos (optional) ───────────────────────────────────────────────────
    is_macos = bool(data.get("is_macos", False))

    # ── Create job ────────────────────────────────────────────────────────────
    primary = wallets[0]

    # Reject if this primary address is already queued or processing — mirroring
    # the web /process endpoint which never spawns a second thread for a running
    # address.  The address-keyed queue cannot serialise two jobs for the same
    # address; both would see themselves at position 0 and proceed concurrently.
    primary_redis = Redis(primary)
    if primary_redis.is_running() or primary_redis.qpos():
        return (
            json.dumps(
                {
                    "error": "A job is already running for this address."
                    " Poll its status or wait before submitting a new one."
                }
            ),
            409,
        )

    job_id = str(uuid.uuid4())

    _set_job_text(job_id, "primary", primary)
    _set_job_text(job_id, "status", "processing")

    t = threading.Thread(
        target=_run_export_job,
        args=(job_id, primary, wallets, currency, dt_config, is_macos, current_app.app_context()),
        daemon=True,
    )
    t.start()

    log("export job submitted", job_id, primary, wallets)
    return json.dumps({"job_id": job_id})


@export_job.route("/api/export/status", methods=["GET"])
def status():
    """
    Poll job status.

    Headers: Authorization: Bearer <DEFITAXES_EXPORT_API_KEY>
    Query params: job_id, address (primary wallet)

    Response 200: { "status": "processing" | "complete" | "failed" [, "error": "..."] }
    Response 400: missing params
    Response 401: invalid or missing API key
    Response 403: wrong primary address
    Response 404: job not found / expired
    """
    denied = _check_api_key()
    if denied:
        return denied

    job_id = (request.args.get("job_id") or "").strip()
    address = normalize_address((request.args.get("address") or "").strip())

    if not job_id or not address:
        return json.dumps({"error": "job_id and address are required"}), 400

    stored_primary = _get_job_text(job_id, "primary")
    if stored_primary is None:
        return json.dumps({"error": "Job not found or expired"}), 404

    if stored_primary != address:
        return json.dumps({"error": "Access denied"}), 403

    job_status = _get_job_text(job_id, "status") or "processing"
    response = {"status": job_status}
    if job_status == "failed":
        response["error"] = _get_job_text(job_id, "error") or "Unknown error"

    return json.dumps(response)


@export_job.route("/api/export/result", methods=["GET"])
def result():
    """
    Download the completed BittyTax XLSX.

    Headers: Authorization: Bearer <DEFITAXES_EXPORT_API_KEY>
    Query params: job_id, address (primary wallet)

    Can be downloaded multiple times within the 3-day TTL.

    Response 200: XLSX attachment
    Response 400: missing params or job not yet complete
    Response 401: invalid or missing API key
    Response 403: wrong primary address
    Response 404: job not found / expired
    Response 410: job complete but result file has expired
    """
    denied = _check_api_key()
    if denied:
        return denied

    job_id = (request.args.get("job_id") or "").strip()
    address = normalize_address((request.args.get("address") or "").strip())

    if not job_id or not address:
        return json.dumps({"error": "job_id and address are required"}), 400

    stored_primary = _get_job_text(job_id, "primary")
    if stored_primary is None:
        return json.dumps({"error": "Job not found or expired"}), 404

    if stored_primary != address:
        return json.dumps({"error": "Access denied"}), 403

    job_status = _get_job_text(job_id, "status")
    if job_status == "failed":
        error = _get_job_text(job_id, "error") or "Unknown error"
        return json.dumps({"error": "Job failed", "details": error}), 400
    if job_status != "complete":
        return json.dumps({"error": "Job is not yet complete", "status": job_status}), 400

    redis_binary = current_app.extensions["redis_binary"]
    redis_prefix = current_app.config["REDIS_PREFIX"]
    excel_data = redis_binary.get(f"{redis_prefix}:job:{job_id}:excel")

    if not excel_data:
        return json.dumps({"error": "Result file has expired"}), 410

    # XLSX is NOT deleted after download; callers may download multiple times within TTL
    bi = io.BytesIO(excel_data)
    return send_file(
        bi,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"BittyTax_Records_{job_id}.xlsx",
        max_age=0,
    )
