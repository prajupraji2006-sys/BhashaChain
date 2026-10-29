"""Opt-in credential verification; never authenticate during test collection."""
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_QPIAI_QUANTUM_INTEGRATION") != "1", reason="Set RUN_QPIAI_QUANTUM_INTEGRATION=1 to contact QpiAI")

def test_qcloud_authentication():
    from dotenv import load_dotenv
    from qpiai_quantum import QpiAIQuantumAuth
    root=Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    key=os.getenv("QCLOUD_API_KEY")
    if not key: pytest.skip("QCLOUD_API_KEY is not configured")
    QpiAIQuantumAuth.login(key)
    assert QpiAIQuantumAuth.verify_api_key() is True
