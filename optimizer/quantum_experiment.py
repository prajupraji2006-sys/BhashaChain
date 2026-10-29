import os

def run_experiment():
    key=os.getenv("QCLOUD_API_KEY","")
    if not key: return {"status":"not_configured","message":"Set QCLOUD_API_KEY and install qpiai-quantum."}
    try:
        from qpiai_quantum import Circuit, QpiAIQuantumAuth
        QpiAIQuantumAuth.login(api_key=key)
        QpiAIQuantumAuth.verify_api_key()
        circuit=Circuit(2,2)
        circuit.h(0); circuit.cx(0,1); circuit.measure([0,1],[0,1])
        result=circuit.run(shots=512,experiment_name="BhashaChain two-option selection toy",device_name="QpiAI-QSV-Local")
        counts=result.get_counts()
        return {"status":"executed","execution_mode":"local_simulator","device":"QpiAI-QSV-Local","shots":512,"counts":{str(k):int(v) for k,v in counts.items()},"classical_comparison":{"ideal_nonzero_outcomes":["00","11"],"ideal_probability_each":0.5,"purpose":"sanity-check expectation for the Bell-state circuit"},"circuit":"Bell state: H(q0), CX(q0,q1), measure both","mapping":"Two equal-cost dataset choices encode a correlated sample; this demonstrates measurement collection only, not optimisation or quantum advantage."}
    except Exception as exc:
        return {"status":"failed","execution_mode":"configured","error":f"{type(exc).__name__}: {exc}"}
