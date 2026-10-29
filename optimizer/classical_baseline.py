from time import perf_counter

def select(candidates, languages, budget, mandatory=()):
    started=perf_counter()
    languages=set(languages); mandatory=set(mandatory)
    valid=[d for d in candidates if d.get("eligible")]
    by_id={d["dataset_id"]:d for d in valid}
    if not mandatory.issubset(by_id):
        valid=[]
    required=[by_id[x] for x in sorted(mandatory) if x in by_id]
    required_cost=sum(float(d["licensing_cost"]) for d in required)
    required_langs={d["language"] for d in required}
    pool=sorted((d for d in valid if d["dataset_id"] not in mandatory),key=lambda d:(float(d["licensing_cost"]),d["dataset_id"]))
    best=None
    def search(index, group, cost, covered):
        nonlocal best
        if cost>budget or (best is not None and cost>best[0][0]): return
        if languages<=covered:
            ids=tuple(sorted(d["dataset_id"] for d in group))
            key=(cost,len(group),ids)
            if best is None or key<best[0]: best=(key,tuple(group))
            return
        missing=languages-covered
        if not any(missing.intersection(d["language"] for d in pool[index:])): return
        if index>=len(pool): return
        item=pool[index]
        search(index+1,group+[item],cost+float(item["licensing_cost"]),covered|{item["language"]})
        search(index+1,group,cost,covered)
    if required_cost<=budget and languages.issubset(required_langs):
        best=((required_cost,len(required),tuple(sorted(mandatory))),tuple(required))
    else:
        search(0,required,required_cost,required_langs)
    if best is None:
        return {"solver":"classical_baseline","execution_mode":"local","feasible":False,"selected_dataset_ids":[],"total_cost":0,"required_languages":sorted(languages),"achieved_languages":[],"objective_value":None,"termination":"INFEASIBLE","budget_feasible":False,"mandatory_compliant":False,"runtime_s":perf_counter()-started}
    group=best[1]
    return {"solver":"classical_baseline","execution_mode":"local","feasible":True,"selected_dataset_ids":sorted(d["dataset_id"] for d in group),"total_cost":best[0][0],"required_languages":sorted(languages),"achieved_languages":sorted({d["language"] for d in group}),"objective_value":best[0][0],"termination":"OPTIMAL_ENUMERATION","budget_feasible":best[0][0]<=budget,"mandatory_compliant":mandatory<=set(d["dataset_id"] for d in group),"runtime_s":perf_counter()-started}
