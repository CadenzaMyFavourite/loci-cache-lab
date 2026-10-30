// Fixed-arrival engine-routing control. Prior benchmark binaries stay intact.
use anyhow::{Context, Result, bail, ensure};
use clap::Parser;
use futures_util::StreamExt;
use loci_cache_lab::{concurrency::Arm, sse::Decoder};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    fs,
    io::Write,
    path::PathBuf,
    sync::Arc,
    time::{Duration, Instant, SystemTime},
};
use tokio::sync::{OwnedSemaphorePermit, Semaphore, mpsc};

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
    #[arg(long, default_value_t = 8)]
    predict: usize,
    #[arg(long, default_value_t = 0)]
    trial: usize,
    #[arg(long, default_value_t = 8192)]
    host_cache_mib: usize,
    #[arg(long, default_value = "f16")]
    kv: String,
    #[arg(long, default_value_t = 12288)]
    context: usize,
    #[arg(long)]
    correctness: bool,
}
#[derive(Clone, Deserialize, Serialize)]
struct Request {
    id: usize,
    conversation: String,
    tokens: Vec<u32>,
    expected: String,
    phase: String,
    arrival_ms: f64,
}
#[derive(Deserialize)]
struct Fixture {
    schema_version: usize,
    scope: String,
    seed: u64,
    requests: Vec<Request>,
}
#[derive(Clone)]
struct State {
    client: reqwest::Client,
    options: Options,
    origin: Instant,
}
fn us(origin: Instant) -> f64 {
    origin.elapsed().as_secs_f64() * 1e6
}
fn payload(r: &Request, predict: usize, correctness: bool) -> Value {
    json!({"prompt":r.tokens,"stream":true,"cache_prompt":true,"id_slot":-1,
        "n_predict":predict,"temperature":0,"seed":42,"ignore_eos":!correctness,
        "return_tokens":true,"timings_per_token":true,"return_progress":false})
}
struct Ready {
    request: Request,
    planned: f64,
    created: f64,
}
async fn one(ctx: State, ready: Ready, admitted: f64, permit: OwnedSemaphorePermit) -> Value {
    let Ready {
        request: r,
        planned,
        created,
    } = ready;
    let mut events = vec![
        json!({"event":"scheduled_arrival","at_us":planned}),
        json!({"event":"created","at_us":created}),
        json!({"event":"queue_enter","at_us":created}),
        json!({"event":"admitted","at_us":admitted}),
    ];
    let body = payload(&r, ctx.options.predict, ctx.options.correctness);
    // This string is both the exact transmitted body and saved evidence.
    let wire = serde_json::to_string(&body).unwrap();
    let mut dispatch = None;
    let mut headers = None;
    let mut first_bytes = None;
    let mut first_sse = None;
    let mut content = None;
    let mut terminal_at = None;
    let mut eof = None;
    let mut terminal = None;
    let mut output = String::new();
    let mut tokens = vec![];
    let result: Result<()> = async {
        dispatch = Some(us(ctx.origin));
        events.push(json!({"event":"http_dispatch","at_us":dispatch}));
        let response = ctx
            .client
            .post(format!("{}/completion", ctx.options.server))
            .header("X-Loci-Request-Id", r.id)
            .header("content-type", "application/json")
            .body(wire.clone())
            .send()
            .await?;
        headers = Some(us(ctx.origin));
        events.push(
            json!({"event":"http_headers","at_us":headers,"status":response.status().as_u16()}),
        );
        if !response.status().is_success() {
            bail!("HTTP {}: {}", response.status(), response.text().await?);
        }
        let mut stream = response.bytes_stream();
        let mut decoder = Decoder::default();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk?;
            if first_bytes.is_none() {
                first_bytes = Some(us(ctx.origin));
            }
            for v in decoder.push(&chunk)? {
                let at = us(ctx.origin);
                if first_sse.is_none() {
                    first_sse = Some(at);
                }
                if v.get("error").is_some() {
                    bail!("SSE error: {v}");
                }
                if let Some(s) = v["content"].as_str() {
                    if !s.is_empty() && content.is_none() {
                        content = Some(at);
                    }
                    output.push_str(s);
                }
                if let Some(ids) = v["tokens"].as_array() {
                    tokens.extend(ids.iter().filter_map(Value::as_u64).map(|n| n as u32));
                }
                if v["stop"] == true {
                    terminal_at = Some(at);
                    terminal = Some(v.clone());
                }
                events.push(json!({"event":"sse","at_us":at,"detail":v}));
            }
        }
        eof = Some(us(ctx.origin));
        decoder.finish()?;
        ensure!(
            terminal.is_some() && content.is_some(),
            "missing terminal or visible content"
        );
        ensure!(
            terminal.as_ref().unwrap()["truncated"] != true,
            "context truncated"
        );
        Ok(())
    }
    .await;
    events.push(json!({"event":"stream_end","at_us":us(ctx.origin)}));
    drop(permit);
    events.push(json!({"event":"admission_released","at_us":us(ctx.origin)}));
    let other = ["A-796", "B-797", "C-798", "D-799", "E-800", "F-801"]
        .iter()
        .any(|s| *s != r.expected && output.contains(s));
    json!({"schema_version":3,"type":"request","routing":"engine_fifo","request_id":r.id,
        "phase":r.phase,"conversation":r.conversation,"expected":r.expected,"input_tokens":r.tokens.len(),
        "planned_us":planned,"created_us":created,"admitted_us":admitted,"arrival_lateness_ms":(created-planned)/1000.,
        "queue_ms":(admitted-created)/1000.,"http_dispatch_us":dispatch,"headers_us":headers,
        "first_bytes_us":first_bytes,"first_sse_us":first_sse,"first_content_us":content,
        "terminal_us":terminal_at,"eof_us":eof,"done_us":us(ctx.origin),"server_acceptance_us":null,
        "scheduled_ttft_ms":content.map(|t|(t-planned)/1000.),"ttft_ms":content.map(|t|(t-created)/1000.),
        "http_ttft_ms":content.zip(dispatch).map(|(t,d)|(t-d)/1000.),
        "dispatch_delay_ms":dispatch.map(|t|(t-planned)/1000.),"wire_body":wire,
        "success":result.is_ok(),"error":result.err().map(|e|format!("{e:#}")),
        "actual_slot":terminal.as_ref().map(|v|v["id_slot"].clone()),
        "timings":terminal.as_ref().map(|v|v["timings"].clone()),"output":output,"output_tokens":tokens,
        "probe_pass":output.contains(&r.expected)&&!other,"probe_exact":output.trim()==r.expected,"another_known_code":other,"events":events})
}

/// Producer follows the saved clock; dispatcher enforces ordered FIFO and two
/// live HTTP streams. Neither producer nor disk output waits for completions.
async fn phase(ctx: State, requests: Vec<Request>) -> Result<Vec<Value>> {
    let (tx, mut rx) = mpsc::unbounded_channel();
    let phase_origin = Instant::now() + Duration::from_millis(50);
    let origin_us = phase_origin.duration_since(ctx.origin).as_secs_f64() * 1e6;
    let producer_ctx = ctx.clone();
    let producer = tokio::spawn(async move {
        for r in requests {
            let due = phase_origin + Duration::from_secs_f64(r.arrival_ms / 1000.);
            tokio::time::sleep_until(tokio::time::Instant::from_std(due)).await;
            let planned = origin_us + r.arrival_ms * 1000.;
            let created = us(producer_ctx.origin);
            tx.send(Ready {
                request: r,
                planned,
                created,
            })
            .unwrap();
        }
    });
    let gate = Arc::new(Semaphore::new(2));
    let mut tasks = tokio::task::JoinSet::new();
    while let Some(ready) = rx.recv().await {
        let permit = gate.clone().acquire_owned().await?;
        let admitted = us(ctx.origin);
        tasks.spawn(one(ctx.clone(), ready, admitted, permit));
    }
    producer.await?;
    let mut rows = vec![];
    while let Some(r) = tasks.join_next().await {
        rows.push(r?);
    }
    rows.sort_by_key(|r| r["request_id"].as_u64().unwrap());
    Ok(rows)
}

fn validate(fixture: &Fixture, slots: &Value, predict: usize) -> Result<()> {
    ensure!(
        fixture.schema_version == 3,
        "requires Phase 3 fixed-arrival fixture"
    );
    let slots = slots.as_array().context("missing slots")?;
    ensure!(slots.len() == 2, "requires two engine slots");
    let capacity = slots
        .iter()
        .filter_map(|s| s["n_ctx"].as_u64())
        .min()
        .context("missing capacity")?;
    let mut ids = std::collections::HashSet::new();
    for label in ["warmup", "measured"] {
        let mut last = -1.;
        for r in fixture.requests.iter().filter(|r| r.phase == label) {
            ensure!(
                r.arrival_ms.is_finite() && r.arrival_ms >= last && r.arrival_ms >= 0.,
                "invalid arrival order"
            );
            ensure!(ids.insert(r.id), "duplicate request ID");
            ensure!(
                r.tokens.len() + predict < capacity as usize,
                "oversized request {}",
                r.id
            );
            last = r.arrival_ms;
        }
    }
    ensure!(ids.len() == fixture.requests.len(), "unknown request phase");
    Ok(())
}
#[tokio::main]
async fn main() -> Result<()> {
    let options = Options::parse();
    ensure!(
        matches!(options.arm, Arm::Fifo | Arm::Corrected),
        "Phase 3 compares FIFO and corrected at concurrency 2"
    );
    ensure!(options.predict > 0, "output limit must be positive");
    let fixture: Fixture = serde_json::from_slice(&fs::read(&options.workload)?)?;
    let client = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(10))
        .timeout(Duration::from_secs(180))
        .build()?;
    let props: Value = client
        .get(format!("{}/props", options.server))
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    let slots: Value = client
        .get(format!("{}/slots", options.server))
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;
    let scope = serde_json::to_string(
        &json!({"model":props["model_path"],"template":props["chat_template"]}),
    )?;
    ensure!(scope == fixture.scope, "model/template scope changed");
    validate(&fixture, &slots, options.predict)?;
    ensure!(
        !options.out.exists(),
        "refusing to overwrite request evidence"
    );
    let ctx = State {
        client,
        options: options.clone(),
        origin: Instant::now(),
    };
    let meta = json!({"schema_version":3,"type":"run","config":options,"seed":fixture.seed,"props":props,"slots":slots,
        "clock":{"origin_unix_ns":SystemTime::now().duration_since(SystemTime::UNIX_EPOCH)?.as_nanos(),
        "units":"monotonic microseconds","arrivals":"saved fixed offsets; two-permit FIFO; traces buffered until both phases finish"}});
    let mut rows = vec![];
    for name in ["warmup", "measured"] {
        rows.extend(
            phase(
                ctx.clone(),
                fixture
                    .requests
                    .iter()
                    .filter(|r| r.phase == name)
                    .cloned()
                    .collect(),
            )
            .await?,
        );
    }
    if let Some(parent) = options.out.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut file = std::io::BufWriter::new(fs::File::create_new(&options.out)?);
    writeln!(file, "{meta}")?;
    for r in &rows {
        writeln!(file, "{r}")?;
    }
    file.flush()?;
    println!(
        "{}: {} request failures retained",
        options.out.display(),
        rows.iter().filter(|r| r["success"] != true).count()
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{Router, body::Body, response::Response, routing::post};
    fn request(id: usize, arrival: f64) -> Request {
        Request {
            id,
            conversation: "A".into(),
            tokens: vec![1; 20],
            expected: "A-796".into(),
            phase: "measured".into(),
            arrival_ms: arrival,
        }
    }
    fn options(url: String) -> Options {
        Options {
            server: url,
            workload: PathBuf::new(),
            out: PathBuf::new(),
            arm: Arm::Fifo,
            predict: 8,
            trial: 0,
            host_cache_mib: 0,
            kv: "f16".into(),
            context: 12288,
            correctness: false,
        }
    }
    #[test]
    fn validates_arrival_order_duplicates_and_capacity() {
        let slots = json!([{"n_ctx":100},{"n_ctx":100}]);
        let mut f = Fixture {
            schema_version: 3,
            scope: "s".into(),
            seed: 1,
            requests: vec![request(0, 0.), request(1, 1.)],
        };
        assert!(validate(&f, &slots, 8).is_ok());
        f.requests[1].arrival_ms = -1.;
        assert!(validate(&f, &slots, 8).is_err());
        f.requests[1].arrival_ms = 1.;
        f.requests[1].id = 0;
        assert!(validate(&f, &slots, 8).is_err());
        f.requests[1].id = 1;
        assert!(validate(&f, &slots, 80).is_err());
    }
    #[tokio::test]
    async fn arrivals_do_not_wait_for_completed_streams_and_fifo_is_preserved() {
        let app=Router::new().route("/completion",post(||async {
            tokio::time::sleep(Duration::from_millis(80)).await;
            Response::builder().header("content-type","text/event-stream").body(Body::from("data: {\"content\":\"A-796\",\"tokens\":[32]}\n\ndata: {\"stop\":true,\"id_slot\":0,\"truncated\":false,\"timings\":{\"cache_n\":19,\"prompt_n\":1}}\n\n")).unwrap()
        }));
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        let ctx = State {
            client: reqwest::Client::new(),
            options: options(format!("http://{address}")),
            origin: Instant::now(),
        };
        let rows = phase(ctx, (0..5).map(|i| request(i, i as f64)).collect())
            .await
            .unwrap();
        assert!(rows.iter().all(|r| r["success"] == true));
        assert!(
            rows[4]["created_us"].as_f64().unwrap() < rows[0]["first_content_us"].as_f64().unwrap()
        );
        assert!(rows[4]["queue_ms"].as_f64().unwrap() > 50.);
        for pair in rows.windows(2) {
            assert!(
                pair[0]["admitted_us"].as_f64().unwrap()
                    <= pair[1]["admitted_us"].as_f64().unwrap()
            );
        }
        server.abort();
    }
}
