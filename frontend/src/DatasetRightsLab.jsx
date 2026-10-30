import React,{useEffect,useMemo,useState}from'react';
import{api,getApiBaseUrl}from'./services/api.js';

const KAGGLE='https://www.kaggle.com/datasets/disisbig/kannada-news-dataset';
const HF='https://huggingface.co/datasets/gaurvar/kannada_news';
const CC='https://creativecommons.org/licenses/by-sa/4.0/';
const initialEvidence=()=>({
 dataset_name:'Kannada News Headlines Dataset',language:'kn',modality:'text',source_url:KAGGLE,
 source_publisher:'disisbig (Kaggle; source-reported)',licence_name:'CC BY-SA 4.0 (source-reported)',licence_url:CC,
 licence_evidence_status:'UNVERIFIED',provenance_status:'NEEDS_REVIEW',intended_purpose:'commercial_training',
 commercial_training:null,attribution_required:true,redistribution_conditions:'Verify the applicable source grant and attribution requirements before use.',
 share_alike_conditions:'If adaptations are shared, verify and follow the applicable same-or-compatible licence conditions.',
 expiry_date:'',expiry_evidence_status:'UNKNOWN',revocation_status:'UNKNOWN',
 evidence_notes:'Hugging Face card reports CC BY-SA 4.0 and around 6,300 headlines. The card marks source-data provenance as More Information Needed. These are source-reported claims; the source grants and underlying article rights have not been independently verified.',
 evidence_timestamp:new Date().toISOString()
});

function parseCsv(text){
 const rows=[];let row=[],cell='',quoted=false;
 for(let i=0;i<text.length;i++){
  const c=text[i];
  if(quoted){if(c==='"'&&text[i+1]==='"'){cell+='"';i++}else if(c==='"')quoted=false;else cell+=c}
  else if(c==='"')quoted=true;
  else if(c===','){row.push(cell);cell=''}
  else if(c==='\n'){row.push(cell);if(row.some(v=>v.trim()!==''))rows.push(row);row=[];cell=''}
  else if(c!=='\r')cell+=c;
 }
 if(quoted)throw new Error('CSV has an unclosed quoted field.');
 if(cell!==''||row.length){row.push(cell);if(row.some(v=>v.trim()!==''))rows.push(row)}
 if(rows.length<2)throw new Error('CSV must contain a header and dataset rows.');
 const headers=rows[0].map((v,i)=>i===0?v.replace(/^\uFEFF/,'').trim():v.trim());
 if(headers.some(v=>!v)||new Set(headers).size!==headers.length)throw new Error('CSV headers must be nonempty and unique.');
 if(!headers.some(v=>v.toLowerCase()==='headline')||!headers.some(v=>v.toLowerCase()==='label'))throw new Error('Expected the dataset card CSV schema: headline,label.');
 const data=rows.slice(1).map((values,index)=>{
  if(values.length!==headers.length)throw new Error(`CSV row ${index+2} has ${values.length} columns; expected ${headers.length}.`);
  return Object.fromEntries(headers.map((key,i)=>[key,values[i]]));
 });
 return{headers,data};
}

async function fileSha256(file){
 const digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
 return Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
}

function Status({value}){const style=value==='ALLOWED'?'green':value==='REJECTED'?'red':'amber';return <span className={`badge ${style}`}>{value}</span>}

export default function DatasetRightsLab({busy,run,result,onPrepareRegistration}){
 const[file,setFile]=useState(null),[rows,setRows]=useState([]),[columns,setColumns]=useState([]),[rowCount,setRowCount]=useState(0),[hash,setHash]=useState(''),[sampleSize,setSampleSize]=useState(20);
 const[geography,setGeography]=useState('');
 const[sourceUrl,setSourceUrl]=useState(KAGGLE),[evidence,setEvidence]=useState(initialEvidence),[storeOriginal,setStoreOriginal]=useState(false);
 const[imports,setImports]=useState([]),[history,setHistory]=useState([]),[benchmarks,setBenchmarks]=useState(null),[manifest,setManifest]=useState(null),[corpus,setCorpus]=useState(null),[message,setMessage]=useState(''),[localError,setLocalError]=useState(''),[editingId,setEditingId]=useState('');
 const[attributionProvided,setAttributionProvided]=useState(null),[willShareAdapted,setWillShareAdapted]=useState(null),[shareAlikeAcknowledged,setShareAlikeAcknowledged]=useState(null);
 const preview=useMemo(()=>rows.slice(0,10),[rows]);
 async function refresh(){try{const[items,decisions]=await Promise.all([api.labDatasets(),api.labHistory()]);setImports(items);setHistory(decisions)}catch(e){setLocalError(e.message)}}
 useEffect(()=>{refresh()},[]);
 function edit(key,value){setEvidence(current=>({...current,[key]:value}))}
 function loadEvidence(item){setEditingId(item.dataset_id);setEvidence({...item.rights_evidence});setSourceUrl(item.source_url)}
 async function saveEvidence(){if(!editingId)return;setLocalError('');try{await api.labUpdateEvidence(editingId,{...evidence,source_url:sourceUrl,expiry_date:evidence.expiry_date||null,evidence_timestamp:new Date().toISOString()});setMessage(`Evidence notes updated for ${editingId}. This remains an operator-provided, unverified evidence record.`);await refresh()}catch(e){setLocalError(e.message)}}
 async function selectFile(next){
  setLocalError('');setMessage('');setManifest(null);setCorpus(null);
  if(!next){setFile(null);setRows([]);setColumns([]);setRowCount(0);setHash('');return}
  if(!next.name.toLowerCase().endsWith('.csv')){setLocalError('Choose a CSV file.');return}
  if(next.size>100*1024*1024){setLocalError('CSV is larger than the 100 MB browser preview limit.');return}
  try{const parsed=parseCsv(await next.text());const digest=await fileSha256(next);setFile(next);setRows(parsed.data);setColumns(parsed.headers);setRowCount(parsed.data.length);setHash(digest);const host=new URL(getApiBaseUrl(),window.location.origin).hostname;setStoreOriginal(host==='localhost'||host==='127.0.0.1'||host==='::1');setEvidence(current=>({...current,dataset_name:current.dataset_name||next.name,source_url:sourceUrl,evidence_timestamp:new Date().toISOString()}))}
  catch(e){setFile(null);setLocalError(e.message)}
 }
 const datasetId=hash?`kn-news-${hash.slice(0,12)}`:'';
 async function importSample(){
  if(!file||!hash)return;
  setLocalError('');setMessage('');
  await run(async()=>{
   const count=Math.min(Math.max(Number(sampleSize)||20,20),50,rowCount);
   if(count<20)throw new Error('At least 20 nonempty CSV rows are required for a demo sample.');
   const sampleRows=rows.slice(0,count);
   const item=await api.labImport({dataset_id:datasetId,filename:file.name,row_count:rowCount,columns,source_url:sourceUrl,file_sha256:hash,sample_rows:sampleRows,rights_evidence:{...evidence,source_url:sourceUrl,expiry_date:evidence.expiry_date||null,evidence_timestamp:new Date().toISOString()}});
   setEditingId(datasetId);
   let stored=null;
   if(storeOriginal)stored=await api.labStoreOriginal(datasetId,file);
   setMessage(stored?`Imported ${count} sample rows; original saved and server hash verified.`:`Imported ${count} sample rows. The full original stayed in this browser and was not uploaded.`);
   await refresh();return item;
  });
 }
 async function checkIngestion(id){
  setLocalError('');
  await run(async()=>{const response=await api.labCheck({dataset_id:id,purpose:'commercial_training',geography,attribution_provided:attributionProvided,will_share_adapted_work:willShareAdapted,share_alike_acknowledged:shareAlikeAcknowledged});setMessage(response.decision==='ALLOWED'?'Policy and verified registry checks passed; sample is training-eligible.':`Decision: ${response.decision}. ${response.reason_codes.join(', ')}`);await refresh();return response});
 }
 async function runBenchmarks(){setLocalError('');try{setBenchmarks(await api.labBenchmarks())}catch(e){setLocalError(e.message)}}
 async function loadManifest(type){setLocalError('');try{setManifest(await api.manifest(type))}catch(e){setLocalError(e.message)}}
 async function downloadManifest(type){setLocalError('');try{const data=await api.manifest(type);setManifest(data);const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));link.download=`${type.replaceAll('_','-')}-manifest.json`;link.click();URL.revokeObjectURL(link.href)}catch(e){setLocalError(e.message)}}
 async function loadCorpus(){setLocalError('');try{setCorpus(await api.labCorpus())}catch(e){setLocalError(e.message)}}
 const displayError=localError;
 return <div className="rights-lab">
  <div className="notice lab-disclaimer"><b>Rights-governance prototype</b><small>Policy output is not legal advice or an automatic legal authority. A source-card label is not independent proof of the underlying creators' rights. Training eligibility additionally requires a valid signed rights record and verified on-chain state.</small></div>
  <section className="panel">
   <div className="panelhead"><div><h3>Import Dataset</h3><p>CSV is parsed in your browser. The full file is not sent unless you explicitly opt into local backend storage.</p></div></div>
   <label className="file-picker">Choose CSV<input type="file" accept=".csv,text/csv" onChange={e=>selectFile(e.target.files?.[0]||null)}/></label>
   <div className="source-links">Dataset sources: <a href={KAGGLE} target="_blank" rel="noreferrer">Kaggle listing</a> · <a href={HF} target="_blank" rel="noreferrer">Hugging Face dataset card</a> · <a href={CC} target="_blank" rel="noreferrer">CC BY-SA 4.0 terms</a></div>
   {file&&<><div className="lab-meta"><div><small>FILENAME</small><b>{file.name}</b></div><div><small>CSV ROWS</small><b>{rowCount.toLocaleString()}</b></div><div><small>COLUMNS</small><b>{columns.join(', ')}</b></div><div><small>SHA-256 (browser-computed)</small><b className="mono hashline">{hash}</b></div><div><small>SOURCE URL</small><b className="source-break">{sourceUrl}</b></div></div>
    <label>Dataset source URL<input value={sourceUrl} onChange={e=>{setSourceUrl(e.target.value);edit('source_url',e.target.value)}}/></label>
    <label>Demo sample rows (20–50)<input type="number" min="20" max="50" value={sampleSize} onChange={e=>setSampleSize(Math.min(50,Math.max(20,Number(e.target.value)||20)))}/></label>
    <label className="inline-check"><input type="checkbox" checked={storeOriginal} onChange={e=>setStoreOriginal(e.target.checked)}/>Also copy the complete original CSV to this backend's ignored `backend/private_data` folder (maximum 25 MB). This uploads the full file.</label>
    {preview.length>0&&<><h4>Preview (up to 10 rows)</h4><div className="tablewrap"><table><thead><tr>{columns.map(col=><th key={col}>{col}</th>)}</tr></thead><tbody>{preview.map((row,i)=><tr key={i}>{columns.map(col=><td key={col}>{row[col]}</td>)}</tr>)}</tbody></table></div></>}
    <button className="primary" disabled={busy||!file||rowCount<20||!sourceUrl.startsWith('https://')} onClick={importSample}>{busy?'Importing…':'Import 20–50 row demo sample'}</button>
   </>}
   {message&&<div className="notice success">{message}</div>}{displayError&&<div className="notice error">{displayError}</div>}
  </section>
  <section className="panel">
   <div className="panelhead"><div><h3>Dataset Metadata &amp; Rights Evidence</h3><p>For the Kaggle dataset, these values start as source-reported claims and remain unverified until evidence is reviewed.</p></div></div>
   <div className="gridform">
    <label>Dataset name<input value={evidence.dataset_name} onChange={e=>edit('dataset_name',e.target.value)}/></label>
    <label>Language code<input value={evidence.language} onChange={e=>edit('language',e.target.value)}/></label>
    <label>Modality<input value={evidence.modality} onChange={e=>edit('modality',e.target.value)}/></label>
    <label>Source publisher<input value={evidence.source_publisher} onChange={e=>edit('source_publisher',e.target.value)}/></label>
    <label>Licence name<input value={evidence.licence_name} onChange={e=>edit('licence_name',e.target.value)}/></label>
    <label>Licence URL<input value={evidence.licence_url} onChange={e=>edit('licence_url',e.target.value)}/></label>
    <label>Licence evidence status<select value={evidence.licence_evidence_status} onChange={e=>edit('licence_evidence_status',e.target.value)}>{['VERIFIED','UNVERIFIED','UNKNOWN','NEEDS_REVIEW'].map(s=><option key={s}>{s}</option>)}</select></label>
    <label>Provenance status<select value={evidence.provenance_status} onChange={e=>edit('provenance_status',e.target.value)}>{['VERIFIED','UNVERIFIED','UNKNOWN','NEEDS_REVIEW'].map(s=><option key={s}>{s}</option>)}</select></label>
    <label>Intended purpose<input value={evidence.intended_purpose} onChange={e=>edit('intended_purpose',e.target.value)}/></label>
    <label>Commercial training permission<select value={evidence.commercial_training===null?'UNKNOWN':String(evidence.commercial_training)} onChange={e=>edit('commercial_training',e.target.value==='UNKNOWN'?null:e.target.value==='true')}><option value="UNKNOWN">UNKNOWN</option><option value="true">YES (evidence required)</option><option value="false">NO</option></select></label>
    <label>Attribution required<select value={evidence.attribution_required===null?'UNKNOWN':String(evidence.attribution_required)} onChange={e=>edit('attribution_required',e.target.value==='UNKNOWN'?null:e.target.value==='true')}><option value="UNKNOWN">UNKNOWN</option><option value="true">YES</option><option value="false">NO</option></select></label>
    <label>Expiry date (ISO date or blank for no expiry)<input type="date" value={(evidence.expiry_date||'').slice(0,10)} onChange={e=>edit('expiry_date',e.target.value?`${e.target.value}T23:59:59Z`:null)}/></label>
    <label>Expiry evidence status<select value={evidence.expiry_evidence_status} onChange={e=>edit('expiry_evidence_status',e.target.value)}>{['VERIFIED','UNVERIFIED','UNKNOWN','NEEDS_REVIEW'].map(s=><option key={s}>{s}</option>)}</select></label>
    <label>Revocation status<select value={evidence.revocation_status} onChange={e=>edit('revocation_status',e.target.value)}>{['ACTIVE','REVOKED','UNKNOWN'].map(s=><option key={s}>{s}</option>)}</select></label>
   </div>
   <label>Redistribution conditions<textarea rows="2" value={evidence.redistribution_conditions} onChange={e=>edit('redistribution_conditions',e.target.value)}/></label>
   <label>ShareAlike conditions<textarea rows="2" value={evidence.share_alike_conditions} onChange={e=>edit('share_alike_conditions',e.target.value)}/></label>
   <label>Evidence notes<textarea rows="4" value={evidence.evidence_notes} onChange={e=>edit('evidence_notes',e.target.value)}/></label>
   <div className="notice">Reported by the mirrored card: Kannada, headline/label CSV fields, approximately 6,300 records, and CC BY-SA 4.0. Its source-provenance section is incomplete. These claims are not independently verified. <b>CC BY-SA allows commercial reuse subject to attribution and ShareAlike terms if adapted material is shared;</b> it is not a blanket commercial-use prohibition.</div>
   {editingId&&<div className="evidence-save"><span>Editing evidence for <b>{editingId}</b></span><button className="soft" onClick={saveEvidence}>Save evidence updates</button></div>}
  </section>
  <section className="panel">
   <div className="panelhead"><div><h3>Check Ingestion</h3><p>Only ALLOWED after evidence policy, signed registry, and chain state all verify.</p></div><button className="soft" onClick={runBenchmarks}>Run synthetic policy benchmark</button></div>
   {imports.length===0?<div className="empty">Import a CSV sample to begin. The actual Kaggle file is not included.</div>:<>
    <div className="lab-check-controls"><label>Requested geography<input value={geography} onChange={e=>setGeography(e.target.value.trim())} placeholder="Enter a region allowed by the provider licence"/></label><label>Attribution will be provided<select value={attributionProvided===null?'UNKNOWN':String(attributionProvided)} onChange={e=>setAttributionProvided(e.target.value==='UNKNOWN'?null:e.target.value==='true')}><option value="UNKNOWN">UNKNOWN</option><option value="true">YES</option><option value="false">NO</option></select></label><label>Will adapted material be shared?<select value={willShareAdapted===null?'UNKNOWN':String(willShareAdapted)} onChange={e=>setWillShareAdapted(e.target.value==='UNKNOWN'?null:e.target.value==='true')}><option value="UNKNOWN">UNKNOWN</option><option value="true">YES</option><option value="false">NO</option></select></label>{willShareAdapted===true&&<label>Will you meet ShareAlike conditions?<select value={shareAlikeAcknowledged===null?'UNKNOWN':String(shareAlikeAcknowledged)} onChange={e=>setShareAlikeAcknowledged(e.target.value==='UNKNOWN'?null:e.target.value==='true')}><option value="UNKNOWN">UNKNOWN</option><option value="true">YES</option><option value="false">NO</option></select></label>}</div>
    <div className="tablewrap"><table><thead><tr><th>DATASET / SOURCE</th><th>ROWS</th><th>SHA-256</th><th>RIGHTS EVIDENCE</th><th>ACTION</th></tr></thead><tbody>{imports.map(item=>{const canPrepare=item.rights_evidence?.licence_evidence_status==='VERIFIED'&&item.rights_evidence?.provenance_status==='VERIFIED'&&item.rights_evidence?.expiry_evidence_status==='VERIFIED'&&item.rights_evidence?.revocation_status==='ACTIVE'&&item.rights_evidence?.commercial_training===true;return <tr key={item.dataset_id}><td><b>{item.dataset_id}</b><small><a href={item.source_url} target="_blank" rel="noreferrer">{item.source_url}</a></small></td><td>{item.row_count}</td><td className="mono">{item.file_sha256.slice(0,20)}…<small>{item.hash_status}{item.original_file_stored?' · original stored':''}</small></td><td><Status value={item.rights_evidence?.licence_evidence_status||'UNKNOWN'}/><small>Provenance: {item.rights_evidence?.provenance_status}</small></td><td><div className="lab-row-actions"><button className="soft" onClick={()=>loadEvidence(item)}>Edit evidence</button><button className="soft" disabled={busy||!geography} onClick={()=>checkIngestion(item.dataset_id)}>Check ingestion</button><button className="soft" disabled={!canPrepare||busy} title={canPrepare?'Prepare signed registration':'Complete rights evidence review first'} onClick={()=>onPrepareRegistration?.({dataset_id:item.dataset_id,content_hash:item.file_sha256,language:item.rights_evidence.language,licence_version:'1.0',issuer:'Provider attestation required',purposes:item.rights_evidence.intended_purpose,regions:'',expires_at:item.rights_evidence.expiry_date||'',derivatives_allowed:false,redistribution_allowed:false,rights_evidence:item.rights_evidence})}>Prepare signed registration</button></div></td></tr>})}</tbody></table></div>
   </>}
   {result?.decision&&result?.policy_version==='bhashachain-ingestion-evidence-v1'&&<div className={`notice ${result.decision==='ALLOWED'?'success':result.decision==='REJECTED'?'error':''}`}><Status value={result.decision}/><small>{result.reason_codes.join(', ')||'Evidence policy, signature, and registry checks passed.'}</small><small>Evidence layer: {result.evidence_layer_result} · signature verified: {String(result.signature_verification?.verified)} · chain: {result.blockchain_verification?.status||'not checked'} · training eligible: {String(result.training_eligible)}</small><small>Decision {result.decision_id} · {result.evaluated_at}</small></div>}
   {benchmarks&&<div className="benchmark-list"><h4>Synthetic cases (evidence-policy layer only)</h4><p>{benchmarks.scope}</p>{benchmarks.cases.map(c=><div className="benchmark-row" key={c.case_id}><b>{c.case_id}. {c.name}</b><span><Status value={c.result.decision}/><small>Expected {c.expected_decision} · {c.result.reason_codes.join(', ')||'all evidence conditions pass'}</small></span></div>)}</div>}
  </section>
  <section className="panel">
   <div className="panelhead"><div><h3>Accepted Corpus Manifest</h3><p>Lab rows enter only when the signed rights record and on-chain registry are both verified.</p></div><div><button className="soft" onClick={()=>{loadManifest('accepted');loadCorpus()}}>Refresh accepted corpus</button> <button className="soft" onClick={()=>downloadManifest('accepted')}>Download JSON</button></div></div>
   {manifest?.manifest==='accepted'&&<div className="manifest-result"><b>{manifest.count} accepted manifest entries</b><small>Manifest SHA-256 {manifest.manifest_hash}</small></div>}
   {corpus&&<div className="manifest-result"><b>{corpus.count} verified sample(s) available to the demo training input</b><small>Rejected and review-pending decisions are filtered server-side.</small></div>}
  </section>
  <section className="panel">
   <div className="panelhead"><div><h3>Rejected / Needs Review Manifest</h3><p>Review-pending imports never appear in the accepted training-corpus endpoint.</p></div><div><button className="soft" onClick={()=>loadManifest('rejected')}>Rejected</button> <button className="soft" onClick={()=>loadManifest('needs_review')}>Needs Review</button> <button className="soft" onClick={()=>downloadManifest('rejected')}>Rejected JSON</button> <button className="soft" onClick={()=>downloadManifest('needs_review')}>Review JSON</button></div></div>
   {manifest&&manifest.manifest!=='accepted'&&<div className="manifest-result"><b>{manifest.count} {manifest.manifest} entries</b><small>Manifest SHA-256 {manifest.manifest_hash}</small></div>}
   {manifest&&<details><summary>Inspect {manifest.manifest} manifest entries</summary><pre>{JSON.stringify(manifest.entries,null,2)}</pre></details>}
  </section>
  <section className="panel"><div className="panelhead"><div><h3>Audit History</h3><p>Rights-lab decisions are saved with policy version, reason codes, file hash, and timestamp.</p></div></div>{history.length===0?<div className="empty">No ingestion decisions yet.</div>:<div className="tablewrap"><table><thead><tr><th>DATASET</th><th>FILE SHA-256</th><th>USE</th><th>DECISION</th><th>REASONS</th><th>TIME</th></tr></thead><tbody>{history.map(item=><tr key={item.decision_id}><td>{item.dataset_id}</td><td className="mono">{item.file_sha256.slice(0,16)}…</td><td>{item.intended_use}</td><td><Status value={item.decision}/></td><td>{item.reason_codes.join(', ')||'—'}</td><td>{new Date(item.evaluated_at).toLocaleString()}</td></tr>)}</tbody></table></div>}</section>
 </div>
}
