"""Opt-in remote quantum test; never submits jobs during normal pytest runs."""
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_QPIAI_QUANTUM_INTEGRATION") != "1", reason="Set RUN_QPIAI_QUANTUM_INTEGRATION=1 to submit a QpiAI experiment")

def test_qcloud_quantum_job():
    from dotenv import load_dotenv
    from qpiai_quantum import Circuit, QpiAIQuantumAuth
    root=Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    key=os.getenv("QCLOUD_API_KEY")
    if not key: pytest.skip("QCLOUD_API_KEY is not configured")
    QpiAIQuantumAuth.login(api_key=key)
    assert QpiAIQuantumAuth.verify_api_key() is True
    circuit=Circuit(2,2)
    circuit.h(0); circuit.cx(0,1); circuit.measure([0,1],[0,1])
    result=circuit.run(shots=32,experiment_name="BhashaChain-Test-01",device_name="QpiAI-QSV-Simulator")
    assert result.get_counts()
