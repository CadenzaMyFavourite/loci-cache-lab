use anyhow::{Context, Result, bail, ensure};
use clap::Parser;
use futures_util::{StreamExt, stream};
use loci_cache_lab::{
    concurrency::{Arm, Routing},
    sse::Decoder,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    fs::{self, File},
    io::{BufWriter, Write},
    path::PathBuf,
    sync::{Arc, Mutex},
    time::{Duration, Instant, SystemTime},
};
use tokio::sync::Semaphore;

#[derive(Parser, Clone, Serialize)]
struct Options {
    #[arg(long, default_value = "http://127.0.0.1:8087")]
    server: String,
    #[arg(long)]
    workload: PathBuf,
    #[arg(long)]
    out: PathBuf,
    #[arg(long, value_enum)]
    arm: Arm,
    #[arg(long, default_value_t = 0)]
    trial: usize,
    #[arg(long, default_value_t = 8192)]
    host_cache_mib: usize,
    #[arg(long, default_value_t = 60)]
    requests: usize,
    #[arg(long)]
    correctness: bool,
    #[arg(long)]
    progress: bool,
    #[arg(long)]
    snapshots: bool,
    #[arg(long, default_value_t = 0)]
    release_delay_ms: u64,
    #[arg(long, default_value = "default")]
    transport: String,
}
#[derive(Clone, Deserialize)]
struct Request {
    id: usize,
    conversation: String,
    tokens: Vec<u32>,
    expected: String,
    phase: String,
}
#[derive(Deserialize)]
struct Fixture {
    schema_version: usize,
    name: String,
    scope: String,
    seed: u64,
    requests: Vec<Request>,
}
#[derive(Clone)]
struct ContextState {
    options: Options,
    client: reqwest::Client,
    routing: Arc<Mutex<Routing>>,
    gate: Arc<Semaphore>,
    start: Instant,
}
fn stamp(start: Instant) -> f64 {
    start.elapsed().as_secs_f64() * 1e6
}
type Events = Arc<Mutex<Vec<Value>>>;
fn event(events: &Events, start: Instant, name: &str, detail: Value) {
    events
        .lock()
        .unwrap()
        .push(json!({"event":name,"at_us":stamp(start),"detail":detail}));
}
struct Lease {
    routing: Arc<Mutex<Routing>>,
    slot: Option<usize>,
    arm: Arm,
    events: Events,
    start: Instant,
}
impl Drop for Lease {
    fn drop(&mut self) {
        if let Some(slot) = self.slot.take() {
            self.routing.lock().unwrap().invalidate(slot);
            event(
                &self.events,
                self.start,
                "slot_invalidated",
                json!({"slot":slot,"cause":"error_or_cancellation"}),
            );
        }
    }
}

async fn one(ctx: ContextState, request: Request, created: f64) -> Value {
    let events = Arc::new(Mutex::new(vec![
        json!({"event":"created","at_us":created,"detail":{}}),
    ]));
    event(&events, ctx.start, "queue_enter", json!({}));
    let queued = stamp(ctx.start);
    let permit = if ctx.options.arm.gated() {
        Some(ctx.gate.clone().acquire_owned().await.unwrap())
    } else {
        None
    };
    let admitted = stamp(ctx.start);
    event(
        &events,
        ctx.start,
        "admitted",
        json!({"gate":ctx.options.arm.gated()}),
    );
    let schedule_start = stamp(ctx.start);
    let busy_before = ctx.routing.lock().unwrap().busy();
    let decision = if ctx.options.arm.explicit() {
        ctx.routing
            .lock()
            .unwrap()
            .reserve(ctx.options.arm, &request.conversation, &request.tokens)
    } else {
        None
    };
    let schedule_us = stamp(ctx.start) - schedule_start;
    if let Some(d) = &decision {
        event(
            &events,
            ctx.start,
            "slot_reserved",
            json!({"decision":d,"busy_before":busy_before}),
        );
    }
    let mut lease = Lease {
        routing: ctx.routing.clone(),
        slot: decision.as_ref().map(|d| d.slot),
        arm: ctx.options.arm,
        events: events.clone(),
        start: ctx.start,
    };
    let mut output = String::new();
    let mut tokens: Vec<u32> = vec![];
    let mut terminal = None;
    let mut before_slots = None;
    let mut final_seen = None;
    let mut first_content = None;
    let mut headers = None;
    let mut first_event = None;
    let mut first_bytes = None;
    let mut dispatch = None;
    let mut eof = None;
    let result:Result<()>=async {
        ensure!(!ctx.options.arm.explicit() || decision.is_some(),"no free slot despite the two-request window");
        if ctx.options.snapshots {
            let t=stamp(ctx.start);
            before_slots=Some(ctx.client.get(format!("{}/slots",ctx.options.server)).send().await?.error_for_status()?.json::<Value>().await?);
            event(&events,ctx.start,"diagnostic_slots_snapshot",json!({"begin_us":t,"slots":before_slots}));
        }
        let body=json!({"prompt":request.tokens,"stream":true,"cache_prompt":true,"id_slot":decision.as_ref().map(|d|d.slot as i64).unwrap_or(-1),"n_predict":if ctx.options.correctness {32} else {8},"temperature":0,"seed":42,"ignore_eos":!ctx.options.correctness,"return_tokens":true,"timings_per_token":true,"return_progress":ctx.options.progress});
        dispatch=Some(stamp(ctx.start));
        event(&events,ctx.start,"http_dispatch",json!({"id_slot":body["id_slot"]}));
        let response=ctx.client.post(format!("{}/completion",ctx.options.server)).header("X-Loci-Request-Id",request.id).json(&body).send().await?;
        headers=Some(stamp(ctx.start));
        event(&events,ctx.start,"http_headers",json!({"status":response.status().as_u16()}));
        if !response.status().is_success() {bail!("HTTP {}: {}",response.status(),response.text().await?);}
        let mut bytes=response.bytes_stream();
        let mut decoder=Decoder::default();
        while let Some(chunk)=bytes.next().await {
            let chunk=chunk?;
            if first_bytes.is_none() {first_bytes=Some(stamp(ctx.start));event(&events,ctx.start,"first_bytes",json!({"bytes":chunk.len()}));}
            for value in decoder.push(&chunk)? {
                if first_event.is_none() {first_event=Some(stamp(ctx.start));}
                event(&events,ctx.start,"sse",value.clone());
                if value.get("error").is_some() {bail!("SSE error: {value}");}
                if let Some(content)=value["content"].as_str() {
                    if !content.is_empty() && first_content.is_none() {first_content=Some(stamp(ctx.start));event(&events,ctx.start,"first_content",json!({}));}
                    output.push_str(content);
                }
                if let Some(ids)=value["tokens"].as_array() {tokens.extend(ids.iter().filter_map(Value::as_u64).map(|n|n as u32));}
                if value["stop"]==true {
                    final_seen=Some(stamp(ctx.start));
                    event(&events,ctx.start,"terminal_received",json!({"slot":value["id_slot"]}));
                    terminal=Some(value);
                }
            }
        }
        eof=Some(stamp(ctx.start));
        event(&events,ctx.start,"stream_eof",json!({}));
        decoder.finish()?;
        ensure!(terminal.is_some() && first_content.is_some(),"missing terminal event or visible output");
        ensure!(terminal.as_ref().unwrap()["truncated"]!=true,"context truncated");
        Ok(())
    }.await;
    let mut error = None;
    match result {
        Ok(()) => {
            if let Some(slot) = lease.slot.take() {
                if ctx.options.release_delay_ms > 0 {
                    tokio::time::sleep(Duration::from_millis(ctx.options.release_delay_ms)).await;
                }
                let mut known = request.tokens.clone();
                known.extend_from_slice(&tokens[..tokens.len().saturating_sub(1)]);
                ctx.routing.lock().unwrap().finish(
                    lease.arm,
                    slot,
                    request.conversation.clone(),
                    known,
                );
                event(&events, ctx.start, "slot_released", json!({"slot":slot}));
            }
        }
        Err(e) => {
            error = Some(format!("{e:#}"));
        }
    }
    drop(lease);
    drop(permit);
    event(&events, ctx.start, "admission_released", json!({}));
    let timing = terminal
        .as_ref()
        .map(|v| v["timings"].clone())
        .unwrap_or(Value::Null);
    let other = ["A-796", "B-797", "C-798", "D-799", "E-800", "F-801"]
        .iter()
        .any(|c| *c != request.expected && output.contains(c));
    json!({"schema_version":2,"type":"request","request_id":request.id,"conversation":request.conversation,"phase":request.phase,"input_tokens":request.tokens.len(),"expected":request.expected,"arm":ctx.options.arm,"trial":ctx.options.trial,"host_cache_mib":ctx.options.host_cache_mib,"created_us":created,"queue_ms":(admitted-queued)/1000.,"schedule_us":schedule_us,"http_dispatch_us":dispatch,"headers_us":headers,"first_bytes_us":first_bytes,"first_sse_us":first_event,"first_content_us":first_content,"terminal_us":final_seen,"eof_us":eof,"done_us":stamp(ctx.start),"server_acceptance_us":null,"ttft_ms":first_content.map(|t|(t-created)/1000.),"http_ttft_ms":first_content.zip(dispatch).map(|(t,s)|(t-s)/1000.),"success":error.is_none(),"error":error,"decision":decision,"busy_before":busy_before,"actual_slot":terminal.as_ref().map(|v|v["id_slot"].clone()),"timings":timing,"output":output,"output_tokens":tokens,"probe_exact":output.trim()==request.expected,"probe_pass":output.contains(&request.expected)&&!other,"another_known_code":other,"slot_snapshot":before_slots,"events":events.lock().unwrap().clone()})
}

#[tokio::main]
async fn main() -> Result<()> {
    let options = Options::parse();
    let fixture: Fixture = serde_json::from_slice(&fs::read(&options.workload)?)?;
    ensure!(
        fixture.schema_version == 1 && fixture.name == "skewed-2048",
        "requires the original skewed-2048 fixture"
    );
    let client = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(10))
        .timeout(Duration::from_secs(180));
    let client = match options.transport.as_str() {
        "default" => client,
        "fresh" => client.pool_max_idle_per_host(0),
        _ => bail!("unknown transport control"),
    }
    .build()?;
    let props: Value = client
        .get(format!("{}/props", options.server))
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    let actual_scope = serde_json::to_string(
        &json!({"model":props["model_path"],"template":props["chat_template"]}),
    )?;
    ensure!(
        actual_scope == fixture.scope,
        "model/template scope changed"
    );
    let slots: Value = client
        .get(format!("{}/slots", options.server))
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    ensure!(
        slots.as_array().context("slots array missing")?.len() == 2,
        "requires two slots"
    );
    for r in &fixture.requests {
        ensure!(
            r.tokens.len() + 32 < slots[0]["n_ctx"].as_u64().unwrap() as usize,
            "oversized request"
        );
    }
    let start = Instant::now();
    let unix_ns = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)?
        .as_nanos();
    let ctx = ContextState {
        options: options.clone(),
        client,
        routing: Arc::new(Mutex::new(Routing::new(fixture.scope))),
        gate: Arc::new(Semaphore::new(2)),
        start,
    };
    if let Some(parent) = options.out.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut writer = BufWriter::new(File::create(&options.out)?);
    writeln!(
        writer,
        "{}",
        json!({"schema_version":2,"type":"run","config":options,"workload":fixture.name,"seed":fixture.seed,"clock":{"client_origin_unix_ns":unix_ns,"events":"monotonic microseconds from process run origin","server_acceptance":"unavailable; headers follow engine START in b11960"},"props":props,"slots":slots})
    )?;
    let mut failures = 0;
    for phase in ["warmup", "measured"] {
        let limit = if phase == "warmup" {
            6
        } else {
            options.requests
        };
        let jobs = fixture
            .requests
            .iter()
            .filter(|r| r.phase == phase)
            .take(limit)
            .cloned()
            .map(|request| {
                let created = stamp(start);
                one(ctx.clone(), request, created)
            });
        let mut outputs = stream::iter(jobs).buffer_unordered(2);
        while let Some(record) = outputs.next().await {
            if record["success"] != true {
                failures += 1;
            }
            writeln!(writer, "{record}")?;
            writer.flush()?;
        }
    }
    println!(
        "{}: {failures} request failures retained",
        options.out.display()
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{Router, body::Body, response::Response, routing::post};
    use tokio::sync::{Mutex as AsyncMutex, Notify};

    fn context(url: String, arm: Arm) -> ContextState {
        ContextState {
            options: Options {
                server: url,
                workload: PathBuf::new(),
                out: PathBuf::new(),
                arm,
                trial: 0,
                host_cache_mib: 0,
                requests: 1,
                correctness: true,
                progress: false,
                snapshots: false,
                release_delay_ms: 0,
                transport: "default".into(),
            },
            client: reqwest::Client::new(),
            routing: Arc::new(Mutex::new(Routing::new("test".into()))),
            gate: Arc::new(Semaphore::new(2)),
            start: Instant::now(),
        }
    }
    fn request() -> Request {
        Request {
            id: 0,
            conversation: "A".into(),
            tokens: vec![1; 100],
            expected: "A-796".into(),
            phase: "measured".into(),
        }
    }
    fn response() -> Response {
        Response::builder().header("content-type","text/event-stream").body(Body::from("data: {\"content\":\"A-796\",\"tokens\":[32],\"timings\":{\"cache_n\":99,\"prompt_n\":1,\"prompt_ms\":1}}\n\ndata: {\"stop\":true,\"id_slot\":0,\"truncated\":false,\"timings\":{\"cache_n\":99,\"prompt_n\":1,\"prompt_ms\":1}}\n\n")).unwrap()
    }
    #[tokio::test]
    async fn fallback_ignores_stale_client_reservations_and_preserves_fifo_permit() {
        let app = Router::new().route(
            "/completion",
            post(|axum::Json(body): axum::Json<Value>| async move {
                // The native engine can select a newly idle matching slot only
                // if the client did not prematurely pin a different slot.
                assert_eq!(body["id_slot"], -1);
                assert_eq!(body["cache_prompt"], true);
                response()
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        let ctx = context(format!("http://{address}"), Arm::Corrected);
        // Intentionally stale hints: Rust thinks both slots remain occupied.
        for id in ["A", "B"] {
            ctx.routing
                .lock()
                .unwrap()
                .reserve(Arm::Custom, id, &[1; 100])
                .unwrap();
        }
        let record = one(ctx.clone(), request(), 0.).await;
        assert_eq!(record["success"], true);
        assert_eq!(record["decision"], Value::Null);
        assert_eq!(ctx.routing.lock().unwrap().busy(), 2);
        assert_eq!(ctx.gate.available_permits(), 2);
        assert!(
            !record["events"]
                .as_array()
                .unwrap()
                .iter()
                .any(|e| e["event"] == "slot_reserved")
        );
        server.abort();
    }
    #[tokio::test]
    async fn cached_request_can_wait_at_server_without_waiting_at_fifo() {
        let engine = Arc::new(AsyncMutex::new(()));
        let held = engine.clone().lock_owned().await;
        let arrived = Arc::new(Notify::new());
        let signal = arrived.clone();
        let app = Router::new().route(
            "/completion",
            post(move || {
                let engine = engine.clone();
                let signal = signal.clone();
                async move {
                    signal.notify_one();
                    let _busy = engine.lock().await;
                    response()
                }
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        let ctx = context(format!("http://{address}"), Arm::Fifo);
        let job = tokio::spawn(one(ctx, request(), 0.0));
        arrived.notified().await;
        tokio::time::sleep(Duration::from_millis(30)).await;
        drop(held);
        let record = job.await.unwrap();
        assert_eq!(record["success"], true);
        assert_eq!(record["timings"]["prompt_n"], 1);
        assert!(record["ttft_ms"].as_f64().unwrap() >= 30.);
        let headers_wait = (record["headers_us"].as_f64().unwrap()
            - record["http_dispatch_us"].as_f64().unwrap())
            / 1000.;
        assert!(headers_wait >= 30.);
        assert!(record["queue_ms"].as_f64().unwrap() < headers_wait);
        assert!(record["server_acceptance_us"].is_null());
        let names: Vec<_> = record["events"]
            .as_array()
            .unwrap()
            .iter()
            .map(|e| e["event"].as_str().unwrap())
            .collect();
        assert!(
            names.iter().position(|s| *s == "http_dispatch")
                < names.iter().position(|s| *s == "first_content")
        );
        server.abort();
    }
    #[tokio::test]
    async fn cancellation_returns_permit_and_invalidates_reserved_slot() {
        let arrived = Arc::new(Notify::new());
        let signal = arrived.clone();
        let app = Router::new().route(
            "/completion",
            post(move || {
                let signal = signal.clone();
                async move {
                    signal.notify_one();
                    std::future::pending::<Response>().await
                }
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        let ctx = context(format!("http://{address}"), Arm::Custom);
        let job = tokio::spawn(one(ctx.clone(), request(), 0.0));
        arrived.notified().await;
        assert_eq!(ctx.routing.lock().unwrap().busy(), 1);
        job.abort();
        let _ = job.await;
        assert_eq!(ctx.routing.lock().unwrap().busy(), 0);
        assert_eq!(ctx.gate.available_permits(), 2);
        let decision = ctx
            .routing
            .lock()
            .unwrap()
            .reserve(Arm::Custom, "A", &[1; 100])
            .unwrap();
        assert_eq!(decision.reason, "empty");
        server.abort();
    }
}
