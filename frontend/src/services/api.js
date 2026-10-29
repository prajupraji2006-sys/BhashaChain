const BASE=import.meta.env.VITE_API_BASE_URL||(import.meta.env.DEV?'http://localhost:8000':'');
let accessToken='';
export function setAccessToken(value){accessToken=value||''}
async function request(path,options={}){
 const headers={'Content-Type':'application/json',...options.headers};
 if(accessToken)headers.Authorization=`Bearer ${accessToken}`;
 const response=await fetch(`${BASE}${path}`,{...options,headers});
 if(!response.ok){const raw=await response.text();try{const parsed=JSON.parse(raw);throw new Error(typeof parsed.detail==='string'?parsed.detail:JSON.stringify(parsed.detail||parsed))}catch(error){if(error instanceof SyntaxError)throw new Error(raw||`HTTP ${response.status}`);throw error}}
 return response.json();
}
export const api={
 health:()=>request('/health'), authCheck:()=>request('/api/auth/check'),
 datasets:()=>request('/api/datasets'), audit:()=>request('/api/audit'), events:()=>request('/api/audit/events'), integrity:()=>request('/api/audit/integrity'),
 check:x=>request('/api/decisions/check',{method:'POST',body:JSON.stringify(x)}),
 optimize:x=>request('/api/optimization/run',{method:'POST',body:JSON.stringify(x)}),
 dispatch:x=>request('/api/qubo/dispatch',{method:'POST',body:JSON.stringify(x)}),
 quantum:()=>request('/api/quantum/run',{method:'POST'}),
 manifest:type=>request(`/api/manifests/${type}`),
 register:x=>request('/api/datasets',{method:'POST',body:JSON.stringify(x)}),
 revoke:id=>request(`/api/datasets/${encodeURIComponent(id)}/revoke`,{method:'POST'}),
 update:(id,x)=>request(`/api/datasets/${encodeURIComponent(id)}/update`,{method:'POST',body:JSON.stringify(x)}),
 registry:id=>request(`/api/blockchain/registry/${encodeURIComponent(id)}`),
 transaction:hash=>request(`/api/blockchain/transactions/${encodeURIComponent(hash)}`),
 chainEvents:id=>request(`/api/blockchain/events/${encodeURIComponent(id)}`),
 labDatasets:()=>request('/api/rights-lab/datasets'),
 labImport:x=>request('/api/rights-lab/import',{method:'POST',body:JSON.stringify(x)}),
 labUpdateEvidence:(id,x)=>request(`/api/rights-lab/datasets/${encodeURIComponent(id)}/evidence`,{method:'POST',body:JSON.stringify(x)}),
 labStoreOriginal:(id,file)=>request(`/api/rights-lab/datasets/${encodeURIComponent(id)}/store-original`,{method:'POST',headers:{'Content-Type':'text/csv'},body:file}),
 labCheck:x=>request('/api/rights-lab/check',{method:'POST',body:JSON.stringify(x)}),
 labHistory:()=>request('/api/rights-lab/history'),
 labBenchmarks:()=>request('/api/rights-lab/benchmarks'),
 labCorpus:()=>request('/api/rights-lab/accepted-corpus'),
};
