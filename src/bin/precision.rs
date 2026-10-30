// Reuse the exact Phase 3 request/parser path; only offered load differs.
#[allow(dead_code)]
mod shared {
    pub async fn run() -> Result<()> {
        let options = Options::parse();
        ensure!(
            matches!(options.arm, Arm::Fifo | Arm::Corrected),
            "requires engine routing"
        );
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
        ensure!(!options.out.exists(), "refusing to overwrite evidence");
        let ctx = State {
            client,
            options: options.clone(),
            origin: Instant::now(),
        };
        let meta = json!({"schema_version":3,"type":"run","config":options,"seed":fixture.seed,"props":props,"slots":slots,
            "clock":{"origin_unix_ns":SystemTime::now().duration_since(SystemTime::UNIX_EPOCH)?.as_nanos(),
                "load":"two closed-loop clients; prepared prompts; traces buffered until finish"}});
        let mut rows = vec![];
        for name in ["warmup", "measured"] {
            let gate = Arc::new(Semaphore::new(2));
            let jobs = fixture
                .requests
                .iter()
                .filter(|r| r.phase == name)
                .cloned()
                .map(|r| {
                    let ctx = ctx.clone();
                    let gate = gate.clone();
                    async move {
                        let created = us(ctx.origin);
                        let permit = gate.acquire_owned().await.unwrap();
                        let admitted = us(ctx.origin);
                        one(
                            ctx,
                            Ready {
                                request: r,
                                planned: created,
                                created,
                            },
                            admitted,
                            permit,
                        )
                        .await
                    }
                });
            let mut outputs = futures_util::stream::iter(jobs).buffer_unordered(2);
            while let Some(row) = outputs.next().await {
                rows.push(row);
            }
        }
        if let Some(parent) = options.out.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut out = std::io::BufWriter::new(fs::File::create_new(&options.out)?);
        writeln!(out, "{meta}")?;
        for row in &rows {
            writeln!(out, "{row}")?;
        }
        out.flush()?;
        println!(
            "{}: {} failures retained",
            options.out.display(),
            rows.iter().filter(|r| r["success"] != true).count()
        );
        Ok(())
    }
    include!("phase3.rs");
}
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    shared::run().await
}
