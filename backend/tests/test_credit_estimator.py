"""Opt-in QpiAI Cloud check; ordinary unit runs must stay offline and free."""
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_QPIAI_QUANTUM_INTEGRATION") != "1", reason="Set RUN_QPIAI_QUANTUM_INTEGRATION=1 to contact QpiAI")

def test_credit_estimator():
    from dotenv import load_dotenv
    from qpiai_quantum import QpiAIQuantumAuth as Auth
    from qpiai_quantum.creditestimator import CreditEstimator
    root=Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    key=os.getenv("QCLOUD_API_KEY")
    if not key: pytest.skip("QCLOUD_API_KEY is not configured")
    Auth.login(key)
    qasm='''OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];'''
    estimate=CreditEstimator(api_key=key).estimate_for_device(qasm=qasm,device_name="QpiAI-QSV-Simulator")
    assert estimate is not None
