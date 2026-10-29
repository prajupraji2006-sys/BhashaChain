"""QpiAI Opt local MILP adapter; never falls back to platform execution."""
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
import logging
import os
from time import perf_counter

logger = logging.getLogger(__name__)


def _sdk_version():
    try:
        return version("qpiai-opt")
    except PackageNotFoundError:
        return None


def _error_code(exc):
    name = type(exc).__name__
    exception_names = {base.__name__ for base in type(exc).__mro__}
    if exception_names & {"AuthenticationError", "APIError"}:
        return "QPIAI_AUTHENTICATION_OR_SERVICE_ERROR"
    if exception_names & {"Timeout", "TimeoutError", "ConnectionError", "SSLError"}:
        return "QPIAI_AUTH_SERVICE_UNREACHABLE"
    if exception_names & {"ImportError", "ModuleNotFoundError"}:
        return "QPIAI_LOCAL_RUNTIME_UNAVAILABLE"
    if exception_names & {"TypeError", "ValueError", "KeyError"}:
        return "QPIAI_MODEL_OR_RESULT_ERROR"
    return "QPIAI_LOCAL_SOLVER_ERROR"


def _failed(stage, exc, started, languages, sdk_version):
    error_type = type(exc).__name__
    code = _error_code(exc)
    # Never log exception text: SDK/network exceptions may contain credentials,
    # headers, URLs, or request details. Stage and class are sufficient triage.
    logger.warning(
        "QpiAI Opt local execution failed stage=%s code=%s exception_type=%s",
        stage,
        code,
        error_type,
    )
    return {
        "solver": "qpiai_opt",
        "status": "failed",
        "execution_mode": "failed",
        "requested_execution_mode": "local",
        "platform_fallback_enabled": False,
        "sdk_version": sdk_version,
        "error_stage": stage,
        "error_code": code,
        "feasible": None,
        "selected_dataset_ids": [],
        "total_cost": None,
        "required_languages": sorted(languages),
        "achieved_languages": [],
        "budget_feasible": None,
        "mandatory_compliant": None,
        "runtime_s": perf_counter() - started,
        "error": f"QpiAI Opt local execution failed during {stage} ({error_type}; {code}).",
    }


def select_with_qpiai(candidates, languages, budget, mandatory=()):
    """Solve locally with the SDK; key verification is online, solving is local.

    QpiAI Opt 0.0.9 documents authenticated local solving as free and separate
    from platform execution. Platform fallback is disabled explicitly here.
    """
    started = perf_counter()
    sdk_version = _sdk_version()
    key = os.getenv("QPIAI_OPT_API_KEY", "")
    if not key:
        return {
            "solver": "qpiai_opt",
            "status": "not_configured",
            "execution_mode": "not_configured",
            "requested_execution_mode": "local",
            "platform_fallback_enabled": False,
            "sdk_version": sdk_version,
            "feasible": None,
            "selected_dataset_ids": [],
            "total_cost": None,
            "required_languages": sorted(languages),
            "achieved_languages": [],
            "budget_feasible": None,
            "mandatory_compliant": None,
            "runtime_s": 0.0,
            "error_code": "QPIAI_OPT_KEY_NOT_CONFIGURED",
            "error": "QPIAI_OPT_API_KEY is not configured",
        }

    stage = "sdk_import"
    try:
        from qpiai_opt.opt_modeller import Binary, Model
        from qpiai_opt.opt_solvers import Client, solve

        stage = "candidate_validation"
        items = [item for item in candidates if item.get("eligible")]
        missing_mandatory = set(mandatory) - {item["dataset_id"] for item in items}
        if not items or missing_mandatory:
            missing = sorted(missing_mandatory)
            return {
                "solver": "qpiai_opt",
                "status": "infeasible",
                "execution_mode": "not_run",
                "requested_execution_mode": "local",
                "platform_fallback_enabled": False,
                "sdk_version": sdk_version,
                "feasible": False,
                "selected_dataset_ids": [],
                "total_cost": 0.0,
                "required_languages": sorted(languages),
                "achieved_languages": [],
                "budget_feasible": False,
                "mandatory_compliant": not missing,
                "runtime_s": perf_counter() - started,
                "error_code": "NO_ELIGIBLE_CANDIDATES" if not items else "MANDATORY_DATASET_INELIGIBLE",
                "error": "No eligible candidates" if not items else "Mandatory datasets are not eligible: " + ", ".join(missing),
            }

        stage = "model_build"
        variables = [Binary(f"d{index}") for index in range(len(items))]
        model = Model("bhashachain_dataset_selection")
        objective = sum(float(item["licensing_cost"]) * variable for item, variable in zip(items, variables))
        model.minimize(objective)
        model.add_constraint(objective <= float(budget), label="budget")
        for language in languages:
            group = [variable for item, variable in zip(items, variables) if item["language"] == language]
            if not group:
                return {
                    "solver": "qpiai_opt",
                    "status": "infeasible",
                    "execution_mode": "not_run",
                    "requested_execution_mode": "local",
                    "platform_fallback_enabled": False,
                    "sdk_version": sdk_version,
                    "feasible": False,
                    "selected_dataset_ids": [],
                    "total_cost": 0.0,
                    "required_languages": sorted(languages),
                    "achieved_languages": [],
                    "budget_feasible": False,
                    "mandatory_compliant": False,
                    "runtime_s": perf_counter() - started,
                    "error_code": "REQUIRED_LANGUAGE_UNAVAILABLE",
                    "error": f"No eligible dataset for required language {language}",
                }
            model.add_constraint(sum(group) >= 1, label=f"cover_{language}")
        for index, (item, variable) in enumerate(zip(items, variables)):
            model.add_constraint(
                variable == 1 if item["dataset_id"] in mandatory else variable >= 0,
                label=f"mandatory_{index}",
            )

        stage = "local_solve"
        result = solve(
            model,
            mode="local",
            client=Client(api_key=key),
            allow_platform=False,
        )

        stage = "result_validation"
        execution_mode = str(result.execution_mode)
        if execution_mode != "local":
            logger.error(
                "QpiAI Opt returned an unexpected execution mode stage=result_validation requested=local"
            )
            return {
                "solver": "qpiai_opt",
                "status": "failed",
                "execution_mode": execution_mode,
                "requested_execution_mode": "local",
                "platform_fallback_enabled": False,
                "sdk_version": sdk_version,
                "feasible": None,
                "selected_dataset_ids": [],
                "total_cost": None,
                "required_languages": sorted(languages),
                "achieved_languages": [],
                "budget_feasible": None,
                "mandatory_compliant": None,
                "runtime_s": perf_counter() - started,
                "error_stage": stage,
                "error_code": "QPIAI_UNEXPECTED_EXECUTION_MODE",
                "error": "QpiAI Opt returned a mode other than the requested local execution mode.",
            }
        solution = result.solution
        if not isinstance(solution, Mapping):
            raise TypeError("SDK solution is not a mapping")
        selected = []
        for index, item in enumerate(items):
            value = solution.get(f"d{index}")
            if value is not None and float(value) >= 0.5:
                selected.append(item)

        info = result.info()
        common = {
            "solver": "qpiai_opt",
            "requested_execution_mode": "local",
            "execution_mode": execution_mode,
            "platform_fallback_enabled": False,
            "sdk_version": sdk_version,
            "problem_class": str(result.problem_class),
            "required_languages": sorted(languages),
            "objective_value": float(result.objective) if result.objective is not None else None,
            "termination": str(info.termination),
            "guarantee": str(info.guarantee),
            "runtime_s": getattr(result, "compute_time_s", None) or perf_counter() - started,
        }
        if not info.has_usable_solution:
            return {
                **common,
                "status": "no_solution",
                "feasible": False,
                "selected_dataset_ids": [],
                "total_cost": 0.0,
                "achieved_languages": [],
                "budget_feasible": False,
                "mandatory_compliant": False,
                "error_code": "QPIAI_NO_USABLE_LOCAL_SOLUTION",
                "error": "QpiAI Opt local solver returned no usable incumbent",
            }

        selected_ids = {item["dataset_id"] for item in selected}
        chosen_cost = sum(float(item["licensing_cost"]) for item in selected)
        achieved = {item["language"] for item in selected}
        budget_feasible = chosen_cost <= float(budget)
        mandatory_compliant = set(mandatory) <= selected_ids
        if not mandatory_compliant or not set(languages) <= achieved or not budget_feasible or len(selected_ids) != len(selected):
            return {
                **common,
                "status": "invalid_solution",
                "feasible": False,
                "selected_dataset_ids": sorted(selected_ids),
                "total_cost": chosen_cost,
                "achieved_languages": sorted(achieved),
                "termination": "INVALID_SOLUTION",
                "budget_feasible": budget_feasible,
                "mandatory_compliant": mandatory_compliant,
                "error_code": "QPIAI_SOLUTION_VALIDATION_FAILED",
                "error": "SDK solution failed independent budget, coverage, or mandatory-item validation",
            }

        return {
            **common,
            "status": "solved",
            "feasible": bool(info.solution_feasible),
            "selected_dataset_ids": sorted(selected_ids),
            "total_cost": chosen_cost,
            "achieved_languages": sorted(achieved),
            "budget_feasible": budget_feasible,
            "mandatory_compliant": mandatory_compliant,
            "method": str(info.method),
            "optimality_gap": getattr(result, "optimality_gap", None),
            "best_bound": getattr(result, "best_bound", None),
        }
    except Exception as exc:
        return _failed(stage, exc, started, languages, sdk_version)
