"""Facility assignment QUBO with honest QpiAI-local and exact-fallback modes."""
from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
import json
import logging
import os
from pathlib import Path
import re
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
logger = logging.getLogger("bhashachain.qpiai_opt.dispatch")


def _configure_logger():
    if logger.handlers:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("[QPI AI OPT] %(asctime)sZ %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    formatter.converter = __import__("time").gmtime
    file_handler = logging.FileHandler(LOG_DIR / "qpi_ai_opt.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_dispatch(level: int, event: str, trace_id: str, **fields):
    _configure_logger()
    safe = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    logger.log(level, "%s trace_id=%s %s", event, trace_id, safe)


def _sdk_version():
    try:
        return version("qpiai-opt")
    except PackageNotFoundError:
        return None


def _add_square(terms, variables, constant, weight):
    """Add weight * (constant + sum(coeff * binary)) ** 2 to a QUBO."""
    variables = [(name, float(coefficient)) for name, coefficient in variables if coefficient]
    for name, coefficient in variables:
        key = (name, name)
        terms[key] = terms.get(key, 0.0) + weight * (2 * constant * coefficient + coefficient * coefficient)
    for index, (left, left_coefficient) in enumerate(variables):
        for right, right_coefficient in variables[index + 1:]:
            key = tuple(sorted((left, right)))
            terms[key] = terms.get(key, 0.0) + weight * 2 * left_coefficient * right_coefficient
    return weight * constant * constant


def build_qubo(jobs, facilities):
    assignments = {(j, f): f"x_{j}_{f}" for j in range(len(jobs)) for f in range(len(facilities))}
    slack = {}
    variable_names = list(assignments.values())
    for f, facility in enumerate(facilities):
        for bit in range(int(facility["capacity"]).bit_length()):
            name = f"s_{f}_{bit}"
            slack[(f, bit)] = name
            variable_names.append(name)

    cost_bound = sum(max(float(f["cost_per_unit"]) * int(job["units"]) for f in facilities) for job in jobs)
    penalty = cost_bound + 1.0
    terms = {}
    constant = 0.0
    for j, job in enumerate(jobs):
        constant += _add_square(terms, [(assignments[(j, f)], 1) for f in range(len(facilities))], -1, penalty)
        for f, facility in enumerate(facilities):
            name = assignments[(j, f)]
            terms[(name, name)] = terms.get((name, name), 0.0) + float(facility["cost_per_unit"]) * int(job["units"])
            supported = {c.casefold() for c in facility["chemistries"]}
            if job["chemistry"].casefold() not in supported:
                terms[(name, name)] += penalty

    for f, facility in enumerate(facilities):
        capacity_terms = [(assignments[(j, f)], int(job["units"])) for j, job in enumerate(jobs)]
        capacity_terms.extend((slack[(f, bit)], 2 ** bit) for bit in range(int(facility["capacity"]).bit_length()))
        constant += _add_square(terms, capacity_terms, -int(facility["capacity"]), penalty)
    return {"terms": terms, "constant": constant, "assignments": assignments, "variables": variable_names,
            "penalties": {"assignment": penalty, "capacity": penalty, "chemistry": penalty},
            "objective_cost_upper_bound": cost_bound}


def _qubo_energy(qubo, bits):
    energy = qubo["constant"]
    for (left, right), coefficient in qubo["terms"].items():
        energy += coefficient * bits[left] * bits[right]
    return energy


def _decode_assignments(bits, jobs, facilities, qubo):
    output = []
    for j, job in enumerate(jobs):
        selected = [f for f in range(len(facilities)) if float(bits.get(qubo["assignments"][(j, f)], 0)) >= 0.5]
        if len(selected) != 1:
            return None
        output.append((job, facilities[selected[0]]))
    loads = {facility["facility_id"]: 0 for facility in facilities}
    total_cost = 0.0
    for job, facility in output:
        if job["chemistry"].casefold() not in {c.casefold() for c in facility["chemistries"]}:
            return None
        loads[facility["facility_id"]] += int(job["units"])
        if loads[facility["facility_id"]] > int(facility["capacity"]):
            return None
        total_cost += float(facility["cost_per_unit"]) * int(job["units"])
    return output, loads, total_cost


def _exact_local_fallback(qubo, jobs, facilities, trace_id):
    count = len(qubo["variables"])
    if count > 20:
        return {"status": "unavailable", "error_code": "EXACT_FALLBACK_SIZE_LIMIT", "variable_count": count}
    log_dispatch(logging.INFO, "Invoking exact classical QUBO fallback", trace_id,
                 solver="classical_exact_qubo_fallback", variable_count=count, qpi_sdk_invoked=False)
    best = None
    for mask in range(1 << count):
        bits = {name: (mask >> index) & 1 for index, name in enumerate(qubo["variables"])}
        decoded = _decode_assignments(bits, jobs, facilities, qubo)
        if decoded is None:
            continue
        energy = _qubo_energy(qubo, bits)
        selected_ids = tuple(f["facility_id"] for _, f in decoded[0])
        rank = (energy, selected_ids, mask)
        if best is None or rank < best[0]:
            best = (rank, bits, decoded)
    if best is None:
        return {"status": "infeasible", "error_code": "NO_FEASIBLE_ASSIGNMENT", "variable_count": count}
    return {"status": "optimal", "solver": "classical_exact_qubo_fallback", "execution_mode": "local_classical_fallback",
            "bits": best[1], "decoded": best[2], "objective_value": best[2][2], "qubo_energy": best[0][0],
            "variable_count": count, "sdk_version": _sdk_version()}


def _qpiai_local(qubo, jobs, facilities, trace_id):
    key = os.getenv("QPIAI_OPT_API_KEY", "")
    if not key:
        log_dispatch(logging.INFO, "QpiAI SDK invocation skipped; key is not configured", trace_id,
                     solver="qpiai_opt", status="not_configured", qpi_sdk_invoked=False)
        return {"status": "not_configured", "execution_mode": "not_configured", "sdk_version": _sdk_version(),
                "error_code": "QPIAI_OPT_KEY_NOT_CONFIGURED"}
    started = perf_counter()
    try:
        from qpiai_opt.opt_modeller import Binary, Model
        from qpiai_opt.opt_solvers import Client, solve
        variables = {name: Binary(name) for name in qubo["variables"]}
        expression = qubo["constant"]
        for (left, right), coefficient in qubo["terms"].items():
            expression += coefficient * variables[left] if left == right else coefficient * variables[left] * variables[right]
        model = Model("bhashachain_facility_dispatch_qubo")
        model.minimize(expression)
        log_dispatch(logging.INFO, "Invoking QpiAI Opt SDK local solver", trace_id,
                     solver="qpiai_opt", sdk_version=_sdk_version(), mode="local", allow_platform=False,
                     variable_count=len(variables))
        result = solve(model, mode="local", client=Client(api_key=key), allow_platform=False)
        execution_mode = str(result.execution_mode)
        if execution_mode != "local":
            return {"status": "failed", "execution_mode": execution_mode,
                    "error_code": "QPIAI_UNEXPECTED_EXECUTION_MODE", "sdk_version": _sdk_version()}
        info = result.info()
        solution = result.variable_assignment
        if not isinstance(solution, Mapping) or not info.has_usable_solution:
            return {"status": "no_solution", "execution_mode": "local",
                    "error_code": "QPIAI_NO_USABLE_LOCAL_SOLUTION", "termination": str(info.termination),
                    "method": str(info.method), "sdk_version": _sdk_version()}
        if set(solution) != set(qubo["variables"]) or any(
            float(solution[name]) not in (0.0, 1.0) for name in qubo["variables"]
        ):
            return {"status": "invalid_solution", "execution_mode": "local",
                    "error_code": "QPIAI_DISPATCH_RESULT_SHAPE_INVALID", "termination": str(info.termination),
                    "method": str(info.method), "sdk_version": _sdk_version()}
        decoded = _decode_assignments(solution, jobs, facilities, qubo)
        if decoded is None:
            return {"status": "invalid_solution", "execution_mode": "local",
                    "error_code": "QPIAI_DISPATCH_VALIDATION_FAILED", "termination": str(info.termination),
                    "method": str(info.method), "sdk_version": _sdk_version()}
        termination = str(info.termination)
        status = "optimal" if "OPTIMAL" in termination.upper() else "feasible"
        return {"status": status, "solver": "qpiai_opt", "execution_mode": execution_mode,
                "bits": solution, "decoded": decoded, "objective_value": decoded[2],
                "qubo_energy": float(result.objective) if result.objective is not None else None,
                "termination": termination, "method": str(info.method), "runtime_s": getattr(result, "compute_time_s", None) or perf_counter() - started,
                "variable_count": len(variables), "sdk_version": _sdk_version()}
    except Exception as exc:
        error_type = type(exc).__name__
        error_status = getattr(exc, "status_code", None)
        error_code = getattr(exc, "code", None)
        safe_error_code = (
            error_code if isinstance(error_code, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", error_code)
            else None
        )
        log_dispatch(logging.WARNING, "QpiAI Opt local solver failed", trace_id,
                     solver="qpiai_opt", error_type=error_type, execution_mode="local",
                     upstream_http_status=error_status, upstream_error_code=safe_error_code)
        return {"status": "failed", "execution_mode": "failed", "error_code": "QPIAI_LOCAL_SOLVER_ERROR",
                "error_type": error_type, "upstream_http_status": error_status,
                "upstream_error_code": safe_error_code, "sdk_version": _sdk_version()}


def solve_dispatch(payload, trace_id):
    started = perf_counter()
    jobs, facilities = payload["jobs"], payload["facilities"]
    log_dispatch(logging.INFO, "Initializing Facility Dispatch QUBO", trace_id,
                 job_count=len(jobs), facility_count=len(facilities), total_units=sum(x["units"] for x in jobs),
                 jobs=[{"job_id":x["job_id"],"chemistry":x["chemistry"],"units":x["units"]} for x in jobs],
                 facilities=[{"facility_id":x["facility_id"],"capacity":x["capacity"],"chemistries":x["chemistries"],"cost_per_unit":x["cost_per_unit"]} for x in facilities])
    qubo = build_qubo(jobs, facilities)
    log_dispatch(logging.INFO, "Applying Capacity & Chemistry Penalties", trace_id,
                 penalty_weights=qubo["penalties"], variable_count=len(qubo["variables"]),
                 quadratic_terms=len(qubo["terms"]))

    qpi = _qpiai_local(qubo, jobs, facilities, trace_id)
    chosen = qpi
    if qpi.get("status") not in ("optimal", "feasible"):
        fallback = _exact_local_fallback(qubo, jobs, facilities, trace_id)
        if fallback.get("status") == "optimal":
            chosen = fallback
        else:
            chosen = fallback
    decoded = chosen.get("decoded")
    assignments = []
    if decoded:
        for job, facility in decoded[0]:
            assignments.append({"job_id": job["job_id"], "facility_id": facility["facility_id"], "facility_name": facility["name"]})
    selected_facilities = {item["facility_id"] for item in assignments}
    assigned_facility = None
    if len(selected_facilities) == 1 and assignments:
        facility = next(f for f in facilities if f["facility_id"] in selected_facilities)
        assigned_facility = {"facility_id": facility["facility_id"], "name": facility["name"]}
    status = str(chosen.get("status", "unavailable")).upper()
    response = {"trace_id": trace_id, "status": status, "solver": chosen.get("solver", "none"),
                "execution_mode": chosen.get("execution_mode", "unavailable"), "assignments": assignments,
                "assigned_facility": assigned_facility, "objective_value": chosen.get("objective_value"),
                "qubo_energy": chosen.get("qubo_energy"),
                "qubo": {"formulation": "binary quadratic objective with one-facility, capacity-slack, and chemistry penalties",
                         "variable_count": len(qubo["variables"]), "quadratic_terms": len(qubo["terms"]),
                         "penalty_weights": qubo["penalties"]},
                "qpiai_opt": qpi, "duration_ms": round((perf_counter()-started)*1000, 3)}
    if assignments:
        log_dispatch(logging.INFO, f"Solver Status: {status}; assigned facility={assigned_facility['name'] if assigned_facility else 'multiple'}",
                     trace_id, solver=response["solver"], execution_mode=response["execution_mode"],
                     assigned_facility_ids=sorted(selected_facilities), duration_ms=response["duration_ms"],
                     qpiai_status=qpi.get("status"))
    else:
        log_dispatch(logging.ERROR, f"Solver Status: {status}; no facility assignment", trace_id,
                     solver=response["solver"], duration_ms=response["duration_ms"], qpiai_status=qpi.get("status"))
    log_dispatch(logging.INFO, "Dispatch completed", trace_id, duration_ms=response["duration_ms"],
                 solver=response["solver"], status=status)
    return response
