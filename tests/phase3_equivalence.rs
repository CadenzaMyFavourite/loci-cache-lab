// Exercise the preserved Phase 2 implementation itself, not a reimplementation.
#[allow(dead_code)]
mod preserved_path {
    include!("../src/bin/concurrency.rs");

    fn equivalent_context(url: String, arm: Arm) -> ContextState {
        ContextState {
            options: Options {
                server: url,
                workload: PathBuf::new(),
                out: PathBuf::new(),
                arm,
                trial: 0,
                host_cache_mib: 8192,
                requests: 1,
                correctness: false,
                progress: false,
                snapshots: false,
                release_delay_ms: 0,
                transport: "default".into(),
            },
            client: reqwest::Client::new(),
            routing: Arc::new(Mutex::new(Routing::new("scope".into()))),
            gate: Arc::new(Semaphore::new(2)),
            start: Instant::now(),
        }
    }
    #[tokio::test]
    async fn phase2_fifo_and_corrected_wire_body_headers_events_and_state_agree() {
        use axum::{
            Router, body::Body, extract::Json, http::HeaderMap, response::Response, routing::post,
        };
        let captured = Arc::new(Mutex::new(vec![]));
        let observed = captured.clone();
        let app=Router::new().route("/completion",post(move |headers:HeaderMap,Json(body):Json<Value>| {
            observed.lock().unwrap().push((body,headers["x-loci-request-id"].clone(),headers["content-type"].clone()));
            async {Response::builder().header("content-type","text/event-stream").body(Body::from("data: {\"content\":\"\"}\n\ndata: {\"content\":\"A-796\",\"tokens\":[32]}\n\ndata: {\"stop\":true,\"id_slot\":1,\"truncated\":false,\"timings\":{\"cache_n\":19,\"prompt_n\":1}}\n\n")).unwrap()}
        }));
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        let mut records = vec![];
        for arm in [Arm::Fifo, Arm::Corrected] {
            let ctx = equivalent_context(format!("http://{address}"), arm);
            let r = Request {
                id: 7,
                conversation: "A".into(),
                tokens: vec![1; 20],
                expected: "A-796".into(),
                phase: "measured".into(),
            };
            let record = one(ctx.clone(), r, 0.).await;
            assert_eq!(record["success"], true);
            assert!(record["decision"].is_null());
            assert_eq!(ctx.gate.available_permits(), 2);
            assert_eq!(ctx.routing.lock().unwrap().busy(), 0);
            records.push(record);
        }
        let wire = captured.lock().unwrap();
        assert_eq!(wire[0], wire[1]);
        assert_eq!(wire[0].0["id_slot"], -1);
        assert_eq!(wire[0].0["cache_prompt"], true);
        let events = |r: &Value| {
            r["events"]
                .as_array()
                .unwrap()
                .iter()
                .map(|e| e["event"].clone())
                .collect::<Vec<_>>()
        };
        assert_eq!(events(&records[0]), events(&records[1]));
        assert_eq!(records[0]["output_tokens"], records[1]["output_tokens"]);
        server.abort();
    }
    #[tokio::test]
    async fn phase2_both_modes_return_permits_without_mutating_routing_on_cancel() {
        use axum::{Router, routing::post};
        let arrived = Arc::new(tokio::sync::Notify::new());
        let signal = arrived.clone();
        let app = Router::new().route(
            "/completion",
            post(move || {
                let signal = signal.clone();
                async move {
                    signal.notify_one();
                    std::future::pending::<String>().await
                }
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        for arm in [Arm::Fifo, Arm::Corrected] {
            let ctx = equivalent_context(format!("http://{address}"), arm);
            let r = Request {
                id: 7,
                conversation: "A".into(),
                tokens: vec![1; 20],
                expected: "A-796".into(),
                phase: "measured".into(),
            };
            let job = tokio::spawn(one(ctx.clone(), r, 0.));
            arrived.notified().await;
            assert_eq!(ctx.gate.available_permits(), 1);
            job.abort();
            let _ = job.await;
            assert_eq!(ctx.gate.available_permits(), 2);
            assert_eq!(ctx.routing.lock().unwrap().busy(), 0);
        }
        server.abort();
    }
}
