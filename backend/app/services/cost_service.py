def allocate_cost(datasets, total_cost=None):
    total=sum(float(d["licensing_cost"]) for d in datasets) if total_cost is None else float(total_cost)
    denominator=sum(float(d["licensing_cost"]) for d in datasets)
    return {d["dataset_id"]: (total*float(d["licensing_cost"])/denominator if denominator else 0.0) for d in datasets}
