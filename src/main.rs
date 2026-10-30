use anyhow::{Context, Result, bail, ensure};
use clap::{Parser, Subcommand, ValueEnum};
use futures_util::{StreamExt, stream};
use loci_cache_lab::{
    scheduler::{Decision, Scheduler},
    sse::Decoder,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    fs::{self, File},
    io::{BufWriter, Write},
    path::PathBuf,
    process::Command,
    sync::{Arc, Mutex},
    time::{Duration, Instant, SystemTime},
};
use tokio::sync::Semaphore;

#[derive(Parser)]
#[command(version, about)]
struct Cli {
    #[arg(long, default_value = "http://127.0.0.1:8087", global = true)]
    server: String,
    #[command(subcommand)]
    command: Commands,
}
#[derive(Subcommand)]
enum Commands {
    /// Validate hardware headroom and, optionally, the running server.
    Check {
        #[arg(long, default_value_t = 3584)]
        min_free_mib: u64,
        #[arg(long)]
        online: bool,
    },
    /// Create exact-token fixtures using the running model's chat template.
    Prepare {
        #[arg(long, default_value = "workloads")]
        out: PathBuf,
        #[arg(long, default_value_t = 60)]
        requests: usize,
        #[arg(long, default_value_t = 42)]
        seed: u64,
    },
    /// Run a fixture. The orchestrator must reset the engine before each trial.
    Run {
        #[arg(long)]
        workload: PathBuf,
        #[arg(long, value_enum)]
        mode: Mode,
        #[arg(long)]
        out: PathBuf,
        #[arg(long, default_value_t = 1)]
        concurrency: usize,
        #[arg(long, default_value_t = 32)]
        predict: usize,
        #[arg(long, default_value_t = 0)]
        trial: usize,
        #[arg(long, default_value_t = 8192)]
        host_cache_mib: u64,
        #[arg(long, default_value = "f16")]
        kv: String,
        #[arg(long, default_value_t = 12288)]
        context: usize,
        /// Queue every request at once to explicitly measure FIFO burst admission.
        #[arg(long)]
        burst: bool,
        /// Allow EOS and verify a conversation-specific secret in each answer.
        #[arg(long)]
        correctness: bool,
    },
}
#[derive(Clone, Copy, Debug, ValueEnum, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
enum Mode {
    Uncached,
    Stock,
    Custom,
    /// Keep custom sequential routing; delegate concurrent slot choice to llama.cpp.
    Corrected,
}
impl Mode {
    fn explicit(self, concurrency: usize) -> bool {
        self == Self::Custom
            || (self == Self::Corrected
                && loci_cache_lab::concurrency::corrected_uses_explicit_slots(concurrency))
    }
}

#[derive(Clone, Serialize, Deserialize)]
struct Request {
    id: usize,
    conversation: String,
    tokens: Vec<u32>,
    expected: String,
    phase: String,
}
#[derive(Serialize, Deserialize)]
struct Fixture {
    schema_version: u32,
    name: String,
    scope: String,
    seed: u64,
    requests: Vec<Request>,
}

#[derive(Clone)]
struct Engine {
    client: reqwest::Client,
    url: String,
}
impl Engine {
    fn new(url: String) -> Result<Self> {
        Ok(Self {
            client: reqwest::Client::builder()
                .connect_timeout(Duration::from_secs(10))
                .timeout(Duration::from_secs(180))
                .build()?,
            url,
        })
    }
    async fn get(&self, path: &str) -> Result<Value> {
        Ok(self
            .client
            .get(format!("{}{path}", self.url))
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?)
    }
    async fn post(&self, path: &str, body: Value) -> Result<Value> {
        Ok(self
            .client
            .post(format!("{}{path}", self.url))
            .json(&body)
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?)
    }
    async fn tokens(&self, text: &str) -> Result<Vec<u32>> {
        let v = self
            .post(
                "/tokenize",
                json!({"content":text,"add_special":true,"parse_special":true}),
            )
            .await?;
        Ok(serde_json::from_value(v["tokens"].clone())?)
    }
}

fn gpu() -> Result<Value> {
    let output = Command::new("nvidia-smi")
        .args([
            "--query-gpu=name,memory.total,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        ])
        .output()
        .context("nvidia-smi unavailable")?;
    ensure!(output.status.success(), "nvidia-smi failed");
    let text = String::from_utf8(output.stdout)?;
    let columns: Vec<_> = text
        .lines()
        .next()
        .context("no NVIDIA GPU")?
        .split(',')
        .map(str::trim)
        .collect();
    ensure!(columns.len() == 4, "unexpected GPU query response");
    Ok(
        json!({"name":columns[0],"total_mib":columns[1].parse::<u64>()?,"free_mib":columns[2].parse::<u64>()?,"driver":columns[3]}),
    )
}

fn next_random(seed: &mut u64) -> u64 {
    *seed ^= *seed << 13;
    *seed ^= *seed >> 7;
    *seed ^= *seed << 17;
    *seed
}

async fn prepare(engine: &Engine, out: PathBuf, count: usize, seed: u64) -> Result<()> {
    ensure!(count > 0 && seed > 0, "requests and seed must be positive");
    fs::create_dir_all(&out)?;
    let props = engine.get("/props").await?;
    // Full model artifact identity is added by the orchestrator's manifest.
    let scope = serde_json::to_string(
        &json!({"model":props["model_path"],"template":props["chat_template"]}),
    )?;
    let mut bases = std::collections::HashMap::new();
    for length in [512usize, 2048, 4096] {
        for conversation in ["A", "B", "C", "D", "E", "F"] {
            let secret = format!("{conversation}-{}", 731 + conversation.as_bytes()[0] as u32);
            let history = format!("Conversation {conversation} discusses a private garden, its soil, water, seasons, paths, trees, and observations. ").repeat(700);
            let rendered = engine.post("/apply-template",json!({"messages":[
                {"role":"system","content":format!("Conversation {conversation}. Your secret code is {secret}. When asked, reply with only that exact secret code. Never use another conversation's code.")},
                {"role":"user","content":history},
                {"role":"assistant","content":format!("I have read the notes. The exact secret code is {secret}.")},
                {"role":"user","content":"Turn 000. What is your secret code?"}
            ],"add_generation_prompt":true})).await?;
            let full = engine
                .tokens(
                    rendered["prompt"]
                        .as_str()
                        .context("missing rendered template")?,
                )
                .await?;
            ensure!(full.len() > length + 128, "filler is too short");
            // Remove only a middle section of user filler. Keep the system message
            // and all closing role markers and the final short user turn intact.
            let mut exact = full[..length - 128].to_vec();
            exact.extend_from_slice(&full[full.len() - 128..]);
            bases.insert((length, conversation.to_string()), (exact, secret));
        }
    }
    for length in [512usize, 2048, 4096] {
        let patterns: Vec<&str> = if length == 2048 {
            vec!["single", "rotation", "skewed", "mixed"]
        } else {
            vec!["single"]
        };
        for pattern in patterns {
            let mut rng = seed;
            let mut requests = vec![];
            for i in 0..count + 6 {
                let (conversation, size) = match pattern {
                    "rotation" => (["A", "B", "C"][i % 3], length),
                    "skewed" => {
                        let n = next_random(&mut rng) % 10;
                        (
                            if n < 7 {
                                "A"
                            } else if n < 9 {
                                "B"
                            } else {
                                "C"
                            },
                            length,
                        )
                    }
                    "mixed" => {
                        if i % 10 == 9 {
                            (["D", "E", "F"][(i / 10) % 3], 4096)
                        } else if i % 3 == 0 {
                            ("B", 512)
                        } else {
                            ("A", 2048)
                        }
                    }
                    _ => ("A", length),
                };
                let (base, expected) = bases.get(&(size, conversation.to_string())).unwrap();
                let mut tokens = base.clone();
                // A genuine changed final user turn, encoded using this tokenizer.
                // Replace the tokenized 000 counter in the preserved tail.
                let old = engine.tokens("000").await?;
                let new = engine.tokens(&format!("{:03}", i % 1000)).await?;
                if let Some(position) = tokens.windows(old.len()).rposition(|w| w == old) {
                    tokens.splice(position..position + old.len(), new);
                } else {
                    bail!("counter not found in fixture tail");
                }
                requests.push(Request {
                    id: i,
                    conversation: conversation.into(),
                    tokens,
                    expected: expected.clone(),
                    phase: if i < 6 { "warmup" } else { "measured" }.into(),
                });
            }
            let name = format!("{pattern}-{length}");
            let path = out.join(format!("{name}.json"));
            fs::write(
                &path,
                serde_json::to_vec(&Fixture {
                    schema_version: 1,
                    name,
                    scope: scope.clone(),
                    seed,
                    requests,
                })?,
            )?;
            println!("{}", path.display());
        }
    }
    Ok(())
}

struct Lease {
    scheduler: Arc<Mutex<Scheduler>>,
    slot: Option<usize>,
}
impl Drop for Lease {
    fn drop(&mut self) {
        if let Some(slot) = self.slot {
            self.scheduler.lock().unwrap().invalidate(slot);
        }
    }
}

#[derive(Clone)]
struct RunConfig {
    mode: Mode,
    concurrency: usize,
    predict: usize,
    trial: usize,
    host_cache_mib: u64,
    kv: String,
    context: usize,
    correctness: bool,
    burst: bool,
}

async fn one(
    engine: Engine,
    request: Request,
    scope: String,
    config: RunConfig,
    scheduler: Arc<Mutex<Scheduler>>,
    permits: Arc<Semaphore>,
    arrival: Instant,
) -> Value {
    let queued = Instant::now();
    let _permit = permits.acquire_owned().await.unwrap();
    let admitted = Instant::now();
    let schedule_start = Instant::now();
    let decision: Option<Decision> = if config.mode.explicit(config.concurrency) {
        scheduler
            .lock()
            .unwrap()
            .reserve(&request.conversation, &request.tokens, &scope)
    } else {
        None
    };
    let schedule_ms = schedule_start.elapsed().as_secs_f64() * 1000.0;
    let mut lease = Lease {
        scheduler: scheduler.clone(),
        slot: decision.as_ref().map(|d| d.slot),
    };
    let mut record = json!({"schema_version":1,"request_id":request.id,"conversation":request.conversation,"phase":request.phase,"input_tokens":request.tokens.len(),"mode":config.mode,"trial":config.trial,"concurrency":config.concurrency,"predict":config.predict,"host_cache_mib":config.host_cache_mib,"kv":config.kv,"context":config.context,"burst":config.burst,"queue_ms":admitted.duration_since(queued).as_secs_f64()*1000.0,"schedule_ms":schedule_ms,"decision":decision,"output":"","output_tokens":[],"success":false});
    let mut output = String::new();
    let mut generated: Vec<u32> = vec![];
    let mut first = None;
    let mut final_event = None;
    let sent = Instant::now();
    let result: Result<()> = async {
        ensure!(!config.mode.explicit(config.concurrency) || decision.is_some(),"no idle slot despite an admission permit");
        let body = json!({"prompt":request.tokens,"stream":true,"cache_prompt":config.mode!=Mode::Uncached,"id_slot":decision.as_ref().map(|d|d.slot as i64).unwrap_or(-1),"n_predict":config.predict,"temperature":0,"seed":42,"ignore_eos":!config.correctness,"return_tokens":true,"timings_per_token":true});
        let response=engine.client.post(format!("{}/completion",engine.url)).json(&body).send().await?;
        if !response.status().is_success() { bail!("HTTP {}: {}",response.status(),response.text().await?); }
        let mut bytes = response.bytes_stream();
        let mut decoder=Decoder::default();
        while let Some(chunk)=bytes.next().await {
            for event in decoder.push(&chunk?)? {
                if event.get("error").is_some() { bail!("server stream error: {event}"); }
                if let Some(content)=event["content"].as_str() {
                    if !content.is_empty() && first.is_none() { first=Some(Instant::now()); }
                    output.push_str(content);
                }
                if let Some(tokens)=event["tokens"].as_array() {
                    generated.extend(tokens.iter().filter_map(Value::as_u64).map(|n|n as u32));
                }
                if event["stop"]==true { final_event=Some(event); }
            }
        }
        decoder.finish()?;
        ensure!(final_event.is_some(),"stream ended without terminal stop event");
        ensure!(first.is_some(),"stream produced no visible output");
        ensure!(final_event.as_ref().unwrap()["truncated"]!=true,"server truncated the context");
        Ok(())
    }.await;
    if let Some(t) = first {
        record["ttft_ms"] = json!(t.duration_since(arrival).as_secs_f64() * 1000.0);
        record["http_ttft_ms"] = json!(t.duration_since(sent).as_secs_f64() * 1000.0);
    }
    record["total_ms"] = json!(arrival.elapsed().as_secs_f64() * 1000.0);
    record["output"] = json!(output);
    record["output_tokens"] = json!(generated);
    // Keep the upstream counters verbatim, but avoid duplicating the full prompt
    // and sampling configuration on every row (fixtures/config store those).
    let mut compact_final = final_event.clone();
    if let Some(event) = compact_final.as_mut().and_then(Value::as_object_mut) {
        event.remove("prompt");
        event.remove("generation_settings");
    }
    record["server_final"] = json!(compact_final);
    if let Some(event) = &final_event {
        record["reused_prompt_tokens"] = event["timings"]["cache_n"].clone();
        record["evaluated_prompt_tokens"] = event["timings"]["prompt_n"].clone();
        record["prefill_ms"] = event["timings"]["prompt_ms"].clone();
        record["decode_ms"] = event["timings"]["predicted_ms"].clone();
        record["decode_tokens_per_second"] = event["timings"]["predicted_per_second"].clone();
    }
    record["expected"] = json!(request.expected);
    let other_code = ["A-796", "B-797", "C-798", "D-799", "E-800", "F-801"]
        .iter()
        .any(|code| *code != request.expected && output.contains(code));
    record["probe_exact"] = json!(output.trim() == request.expected);
    record["probe_pass"] = json!(output.contains(&request.expected) && !other_code);
    match result {
        Ok(()) => {
            record["success"] = json!(true);
            if let Some(slot) = lease.slot.take() {
                let mut known = request.tokens.clone();
                // The last sampled token may not yet have been evaluated into KV.
                known.extend_from_slice(&generated[..generated.len().saturating_sub(1)]);
                scheduler
                    .lock()
                    .unwrap()
                    .finish(slot, request.conversation, known);
            }
        }
        Err(error) => {
            record["error"] = json!(format!("{error:#}"));
        }
    }
    record
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    let engine = Engine::new(cli.server)?;
    match cli.command {
        Commands::Check {
            min_free_mib,
            online,
        } => {
            let info = gpu()?;
            println!("{info}");
            ensure!(
                info["free_mib"].as_u64().unwrap() >= min_free_mib,
                "insufficient VRAM: need {min_free_mib} MiB free; no settings were changed"
            );
            if online {
                println!("{}", engine.get("/props").await?);
                println!("{}", engine.get("/slots").await?);
            }
        }
        Commands::Prepare {
            out,
            requests,
            seed,
        } => prepare(&engine, out, requests, seed).await?,
        Commands::Run {
            workload,
            mode,
            out,
            concurrency,
            predict,
            trial,
            host_cache_mib,
            kv,
            context,
            burst,
            correctness,
        } => {
            ensure!((1..=2).contains(&concurrency), "concurrency must be 1 or 2");
            ensure!(predict > 0, "predict must be positive");
            let fixture: Fixture = serde_json::from_slice(&fs::read(workload)?)?;
            ensure!(fixture.schema_version == 1, "unsupported fixture schema");
            let slots = engine.get("/slots").await?;
            let slots = slots
                .as_array()
                .context("slots endpoint did not return an array")?;
            ensure!(
                slots.len() == 2,
                "benchmark requires exactly two engine slots"
            );
            let props = engine.get("/props").await?;
            let actual_scope = serde_json::to_string(
                &json!({"model":props["model_path"],"template":props["chat_template"]}),
            )?;
            ensure!(
                actual_scope == fixture.scope,
                "model/template changed: prepare new fixtures"
            );
            let available = slots
                .iter()
                .filter_map(|s| s["n_ctx"].as_u64())
                .min()
                .context("missing per-slot context capacity")? as usize;
            for request in &fixture.requests {
                ensure!(
                    request.tokens.len() + predict < available,
                    "request {} needs {} tokens but slot capacity is {available}",
                    request.id,
                    request.tokens.len() + predict
                );
            }
            if let Some(parent) = out.parent() {
                fs::create_dir_all(parent)?;
            }
            let mut writer = BufWriter::new(File::create(&out)?);
            let config = RunConfig {
                mode,
                concurrency,
                predict,
                trial,
                host_cache_mib,
                kv,
                context,
                correctness,
                burst,
            };
            let scheduler = Arc::new(Mutex::new(Scheduler::new(2, fixture.scope.clone())));
            let permits = Arc::new(Semaphore::new(concurrency));
            let started_unix_ms = SystemTime::now()
                .duration_since(SystemTime::UNIX_EPOCH)?
                .as_millis();
            let meta = json!({"schema_version":1,"type":"run","workload":fixture.name,"seed":fixture.seed,"started_unix_ms":started_unix_ms,"props":props,"slots":slots,"config":{"mode":mode,"concurrency":concurrency,"predict":predict,"trial":trial,"host_cache_mib":host_cache_mib,"kv":config.kv,"context":context,"correctness":correctness,"burst":burst}});
            writeln!(writer, "{meta}")?;
            let requests = fixture.requests;
            let mut failures = 0;
            // Warmup is completed before measurement begins, including with two clients.
            for phase in ["warmup", "measured"] {
                let phase_requests: Vec<_> = requests
                    .iter()
                    .filter(|r| r.phase == phase)
                    .cloned()
                    .collect();
                let width = if burst {
                    phase_requests.len().max(1)
                } else {
                    concurrency
                };
                let common_arrival = Instant::now();
                let jobs = phase_requests.into_iter().map(|request| {
                    let arrival = if burst {
                        common_arrival
                    } else {
                        Instant::now()
                    };
                    one(
                        engine.clone(),
                        request,
                        fixture.scope.clone(),
                        config.clone(),
                        scheduler.clone(),
                        permits.clone(),
                        arrival,
                    )
                });
                let mut results = stream::iter(jobs).buffer_unordered(width);
                while let Some(mut record) = results.next().await {
                    record["workload"] = json!(fixture.name);
                    if record["success"] != true {
                        failures += 1;
                    }
                    writeln!(writer, "{record}")?;
                    writer.flush()?;
                }
            }
            println!("{}: {failures} failed requests", out.display());
            ensure!(
                failures == 0,
                "benchmark contains {failures} failures; inspect JSONL"
            );
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{Router, body::Body, response::Response, routing::post};

    #[test]
    fn corrected_mode_pins_only_sequential_requests() {
        assert!(Mode::Corrected.explicit(1));
        assert!(!Mode::Corrected.explicit(2));
        assert!(Mode::Custom.explicit(2));
        assert!(!Mode::Stock.explicit(1));
    }

    #[tokio::test]
    async fn empty_initial_chunk_and_server_error_release_slot() {
        let app=Router::new().route("/completion",post(|| async {
            Response::builder().header("content-type","text/event-stream").body(Body::from("data: {\"content\":\"\"}\n\ndata: {\"content\":\"A-796\",\"tokens\":[1]}\n\ndata: {\"stop\":true,\"truncated\":false,\"timings\":{}}\n\n")).unwrap()
        }));
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let task = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        let scheduler = Arc::new(Mutex::new(Scheduler::new(2, "scope".into())));
        let config = RunConfig {
            mode: Mode::Custom,
            concurrency: 1,
            predict: 8,
            trial: 0,
            host_cache_mib: 0,
            kv: "f16".into(),
            context: 12288,
            correctness: true,
            burst: false,
        };
        let request = Request {
            id: 0,
            conversation: "A".into(),
            tokens: vec![42; 10],
            expected: "A-796".into(),
            phase: "measured".into(),
        };
        let result = one(
            Engine::new(format!("http://{address}")).unwrap(),
            request.clone(),
            "scope".into(),
            config.clone(),
            scheduler.clone(),
            Arc::new(Semaphore::new(1)),
            Instant::now(),
        )
        .await;
        assert_eq!(result["success"], true);
        assert_eq!(result["probe_pass"], true);
        assert!(result["ttft_ms"].as_f64().unwrap() > 0.0);
        task.abort();
        // Connection refusal after reservation must invalidate the leased slot.
        let result = one(
            Engine::new(format!("http://{address}")).unwrap(),
            request,
            "scope".into(),
            config,
            scheduler.clone(),
            Arc::new(Semaphore::new(1)),
            Instant::now(),
        )
        .await;
        assert_eq!(result["success"], false);
        assert_eq!(
            scheduler
                .lock()
                .unwrap()
                .reserve("B", &[7; 10], "scope")
                .unwrap()
                .reason,
            "empty"
        );
    }

    #[tokio::test]
    async fn cancelled_lease_invalidates_and_fifo_admission() {
        let scheduler = Arc::new(Mutex::new(Scheduler::new(1, "scope".into())));
        let slot = scheduler
            .lock()
            .unwrap()
            .reserve("A", &[1; 10], "scope")
            .unwrap()
            .slot;
        let lease = Lease {
            scheduler: scheduler.clone(),
            slot: Some(slot),
        };
        let task = tokio::spawn(async move {
            let _lease = lease;
            std::future::pending::<()>().await;
        });
        task.abort();
        let _ = task.await;
        assert_eq!(
            scheduler
                .lock()
                .unwrap()
                .reserve("B", &[2; 10], "scope")
                .unwrap()
                .reason,
            "empty"
        );
        let sem = Arc::new(Semaphore::new(1));
        let held = sem.clone().acquire_owned().await.unwrap();
        let mut first = Box::pin(sem.clone().acquire_owned());
        let mut second = Box::pin(sem.clone().acquire_owned());
        assert!(futures_util::poll!(&mut first).is_pending());
        assert!(futures_util::poll!(&mut second).is_pending());
        drop(held);
        let first = first.await.unwrap();
        assert!(futures_util::poll!(&mut second).is_pending());
        drop(first);
        assert!(second.await.is_ok());
    }
}
