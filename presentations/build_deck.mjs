// Optional deck authoring. Inference and demo do not require this runtime.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {Presentation,PresentationFile} from '@oai/artifact-tool';

const root=path.resolve(process.argv[2]||'.');
const skill=process.env.CODEX_PRESENTATIONS_SKILL;
if(!skill)throw new Error('Set CODEX_PRESENTATIONS_SKILL to the installed presentations skill directory');
const runtimePython=process.env.CODEX_PRESENTATIONS_PYTHON;
if(!runtimePython)throw new Error('Set CODEX_PRESENTATIONS_PYTHON to the supplied authoring Python');
const {resolvePresentationFont,applyPresentationChartFont,finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const font=resolvePresentationFont({fontFamily:'Arial'});
const load=async p=>JSON.parse(await fs.readFile(path.join(root,p),'utf8'));
const ablation=(await load('evidence/phase2-summary.json')).groups.ablation;
const tail=await load('evidence/phase3-tail-summary.json');
const trace=await load('evidence/early-binding.json');
const allocation=await load('evidence/allocations.json');
const p=Presentation.create({slideSize:{width:1280,height:720}});
const blue='#16324F',ink='#172B3A';
function text(s,value,x,y,w,h,size=28,bold=false,color=ink){
 const t=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 t.text=value;t.text.style={typeface:font,fontSize:size,bold,color};return t;
}
function slide(title,source){const s=p.slides.add();s.background.fill='#FFFFFF';text(s,title,70,45,1140,85,46,true,blue);s.speakerNotes.text=source;return s;}
function table(s,values,y=165,widths=null,rowHeight=70){
 const t=s.tables.add({rows:values.length,columns:values[0].length,left:70,top:y,width:1140,height:values.length*rowHeight,values,...(widths?{columnWidths:widths}:{})});
 t.borders.assign({fill:'#D5DFE7',width:1,style:'solid'});
 for(let r=0;r<values.length;r++){t.rows[r].height=rowHeight;for(let c=0;c<values[0].length;c++){
  const cell=t.getCell(r,c);cell.fill=r===0?blue:'#FFFFFF';cell.text.style={typeface:font,fontSize:25,color:r===0?'#FFFFFF':ink,bold:r===0};
 }}return t;
}
function note(s,v,y=605){text(s,v,70,y,1140,90,22,false,'#465D6D');}
function chart(s,categories,series,position,yTitle,max){
 const c=s.charts.add('bar',{position,categories,series,barOptions:{direction:'column',grouping:'clustered',gapWidth:90},hasLegend:series.length>1,
  legend:{position:'bottom',overlay:false,textStyle:{fontSize:24}},
  xAxis:{textStyle:{fontSize:24,fill:ink}},yAxis:{min:0,max,title:{text:yTitle,textStyle:{fontSize:24}},textStyle:{fontSize:22},majorGridlines:{fill:'#DFE6EB',width:1,style:'solid'}},
  dataLabels:{showValue:true,position:'outEnd',textStyle:{fontSize:24,fill:ink},numberFormatCode:'0.0'}});
 applyPresentationChartFont(c,{fontFamily:font});return c;
}

let s=slide('Conversation caching on an 8 GB GPU','Sources: README.md; docs/REPORT.md; PHASE2_REPORT.md; PHASE3_REPORT.md. All measurements are retained. No universal Rust speedup is claimed.');
text(s,'Rust routing and tail latency',75,190,1120,140,58,true,blue);
text(s,'Engineering case study',75,360,1100,60,32);
text(s,'RTX 4070 Laptop GPU, 8 GB\nQwen2.5-3B-Instruct Q4_K_M, llama.cpp b11960',75,495,1110,100,28);

s=slide('Native caching provides the baseline gain','Source: docs/REPORT.md, repeated 2,048-token control. Median TTFT 285.5 ms uncached and 18.3 ms stock cached. This is llama.cpp caching, not an effect attributable to Rust. Eight output tokens, synthetic fixed prompts, five paired trials.');
text(s,'Retaining frequent, expensive prefixes might reduce TTFT.\nControl: 2,048 input tokens and eight output tokens.',70,135,1130,80,29);
chart(s,['Uncached','Stock cached'],[{name:'Median TTFT',values:[285.5,18.3],fill:'#2671AA'}],{left:85,top:225,width:1080,height:330},'TTFT (ms)',330);
note(s,'The large measured gain belongs to llama.cpp. Rust routing needs its own controlled comparison.');

s=slide('Rust schedules requests and hints at slot choice','Sources: src/scheduler.rs, src/main.rs, src/concurrency.rs, src/sse.rs. The engine validates token-prefix KV reuse. The heuristic multiplies known cached tokens by frequency over the previous 32 admissions.');
table(s,[['Layer','Responsibility'],['Rust admission','Fair semaphore bounds live requests'],['Original routing','Longest token prefix, then retention score'],['llama.cpp','Validates KV reuse and performs prefill/decode'],['Corrected concurrency','Delegates slot choice with id_slot = -1']],155,[340,800],76);
note(s,'Retention score = cached tokens × frequency in the previous 32 admissions.\nExplicit leases survive until completion. Cancellation invalidates uncertain hints.',570);

s=slide('Removing frequency weighting did not cure the regression','Source: evidence/phase2-summary.json groups.ablation, cache 0 MiB. Five paired trials times 60 measured requests per arm, zero failures. Median is median of trial medians; P95 pools successful requests. Stock here includes FIFO admission.');
const arms=['fifo','lru','custom'].map(a=>ablation.find(r=>r.arm===a&&r.cache===0));
table(s,[['Two-client route','Median TTFT ms','P95 ms'],...arms.map((r,i)=>[['Stock + FIFO','Explicit prefix/LRU','Original custom'][i],r.median_of_trial_medians_ms.toFixed(2),r.p95_ms.toFixed(2)])],180,[570,290,280],85);
note(s,'Median of trial medians; pooled P95. Host cache disabled.\nFIFO wait and routing computation cost microseconds. Both explicit policies regress.',565);

s=slide('A later idle prefix can defeat an early slot decision','Source: evidence/early-binding.json. Recorded verbose Phase 2 diagnostic, request 10/task 59 followed by request 11/task 61. Per-slot task ordering is inferred and validated against exact output token IDs and evaluated counters. Alternate-prefix reconstruction is an opportunity, not alternate-run latency.');
const origin=trace.requests[0].engine.posted_ms;
table(s,[['Engine ms after POST','Observed event'],['0.000','Request 10 enters the native task queue'],[(trace.alternate_released_engine_ms-origin).toFixed(3),'Other slot becomes idle with 2,034 matching tokens'],[(trace.requests[0].engine.selected_ms-origin).toFixed(3),'Pinned slot stays selected, reusing only 4 tokens'],[(trace.requests[1].engine.posted_ms-origin).toFixed(3),'Cached request 11 enters the native task queue'],[(trace.requests[0].engine.first_token_ms-origin).toFixed(3),'Request 10 completes a 2,044-token prefill'],[(trace.requests[1].engine.launched_ms-origin).toFixed(3),'Cached request 11 can launch']],145,[330,810],58);
note(s,'Request 11 reused 2,034 tokens yet waited 287.84 ms from native POST to launch.',565);

s=slide('Corrected concurrency uses stock routing','Sources: docs/phase3-equivalence.md; evidence/phase3-tail-summary.json. Forty trial/cache pairs compare 2,640 exact transmitted JSON bodies. Twenty paired trials per cache, 60 measured requests per arm. Five measured and one warmup connection failures remain. The failure-free no-host-cache interval widens to [-1.08%, +19.26%].');
text(s,'Both use id_slot = -1 and the same fair semaphore.\nChanges below compare corrected with stock.',70,140,1130,75,29);
const pairs=tail.paired;
table(s,[['Host cache MiB','P95 change','95% paired trial interval'],...pairs.map(r=>{const v=r.metrics.ttft_ms.p95;return[String(r.cache),`${v.change_percent.toFixed(2)}%`,v.change_95_percent.map(x=>`${x.toFixed(2)}%`).join(' to ')];})],225,[320,290,530],80);
note(s,'20 paired trials. The default-cache ranking flipped after expansion.\nFailure-free no-host-cache interval: -1.08% to +19.26%. Tail variance remains unresolved.',525);

s=slide('KV precision trades allocation for performance','Sources: evidence/allocations.json; evidence/phase3-precision-summary.json; evidence/phase3-correctness-summary.json. Four selected cases span both contexts, inputs 2048/4096, outputs 32/128. Five paired trials per cell. About 46.9% lower native KV allocation. All eight paired per-stream decode-rate point estimates regress 3.34–5.70%, some intervals include benefit. 120 selected EOS factual probes pass. Numerical/token differences persist.');
const kvs=type=>[9216,16384].map(ctx=>allocation.find(a=>a.context===ctx&&a.kv===type).native_gpu_buffers.KV_mib);
chart(s,['9,216 context','16,384 context'],[{name:'f16',values:kvs('f16'),fill:'#476A89'},{name:'q8_0',values:kvs('q8_0'),fill:'#DC9A37'}],{left:60,top:165,width:740,height:390},'Allocated KV (MiB)',680);
text(s,'46.9% less native KV allocation\n\nDecode-rate point estimates: 3.3–5.7% lower\nSome intervals include gains\n\nTTFT changes are mixed',830,185,360,385,27);
note(s,'Selected cases only. Total VRAM, exact peaks and production accuracy require separate evidence.',590);

s=slide('Limits and next experiments','Sources: PHASE3_REPORT.md; docs/kv-cache-precision.md; docs/CASE_STUDY.md. No specific CUDA or HTTP root cause is asserted for the residual Phase 3 variance.');
table(s,[['Unresolved finding','Next experiment'],['Unstable default-cache P95','More randomized blocks and tighter arrival fidelity'],['Connection closures before headers','Isolate transport with retained failure accounting'],['Numerical and output variation','Compare controlled engine states and log probabilities'],['Single synthetic device/model study','Representative traces and hypothesis-driven GPU profiling']],155,[535,605],83);
note(s,'Stock native routing remains the concurrent recommendation. No universal scheduler or q8_0 speedup is established.',585);

s=slide('A reproducible mini-demo','Sources: scripts/demo.py; demo.ps1; docs/DEMO.md; docs/RECORDING_GUIDE.md. The live demo is a smoke test, not a repeated experiment. The original failure is shown using the recorded trace, not a staged live failure. No video was fabricated.');
text(s,'1. Validate the existing model and engine\n2. Run stock, custom and corrected routes\n3. Inspect request counters and the small comparison chart\n4. Walk through the recorded early-binding trace',75,175,1120,295,32);
text(s,'.\\demo.ps1',75,510,1100,65,38,true,blue);
note(s,'The live sample cannot establish a speedup or guarantee replay of a timing-sensitive failure.',605);

// Use a fresh authoring directory. Never overwrite an existing validation receipt.
const build=path.resolve(root,process.argv[3]||`runs/deck-build-${Date.now()}`);await fs.mkdir(build,{recursive:true});
for(const [i,sl]of p.slides.items.entries()){
 const blob=await p.export({slide:sl,format:'png',scale:1});await fs.writeFile(path.join(build,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
}
const draft=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(p)).save(draft);
const output=path.join(build,'output');await fs.mkdir(output,{recursive:true});
const final=path.join(output,'engineering-case-study.pptx');
await finalizePresentation({workspaceDir:root,candidatePath:draft,finalPath:final,pythonExecutable:runtimePython,
 integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit',...[3,4,5,6,8].flatMap(n=>['--require-native-table-slide',String(n)])],
 requiredNativeTableOwnerSlides:[3,4,5,6,8],requiredNativeChartOwnerSlides:[2,7],explicitTotalSlideCount:9,
 materializeLiteralChartWorkbooks:true,verifyArtifactToolImport:true,fontPolicy:{basis:'design',families:[font]},
 receiptPath:path.join(build,'validation.json')});
console.log(final);
