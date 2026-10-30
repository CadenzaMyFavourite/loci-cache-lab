# Presentation storyboard and manual recording guide

No video or screen recording was produced. The editable [nine-slide case study](../presentations/engineering-case-study.pptx) and the steps below support a manual recording. Use a recorder you already have, capture only the intended application region, and hide unrelated windows/notifications. Prefer the portable publication tree so personal paths are absent from displayed historical evidence.

## Suggested 90-second storyboard

| Time | Screen | Explanation |
|---|---|---|
| 0–12 s | README question and baseline slide | Three conversations, two slots. The 285.5/18.3 ms gain belongs to native caching |
| 12–30 s | Recorded trace slide or `evidence/early-binding.json` | Rust committed before another matching slot became idle. Show 4 reused / 2,044 evaluated tokens and the next request's 287.84 ms wait |
| 30–57 s | Terminal running `.\demo.ps1` | Show the real reset/prepare/three-arm smoke run. The observed release run took about 25 seconds |
| 57–70 s | Generated `summary.json` / `comparison.png` | Check failures and evaluated/reused counters before latency. One trial cannot rank the modes |
| 70–83 s | Corrected routing and KV slides | Corrected mode delegates native slot selection. q8_0 saves allocation while throughput/TTFT need separate evidence |
| 83–90 s | Final case-study slide | Stock remains the concurrent default. Point to code, evidence and unresolved questions |

The original failure segment is a walkthrough of **saved measured evidence**, not a claim that the live smoke run reproduces that interleaving. Do not stage the request timings, replace counter values, or describe a reconstructed alternate prefix as an observed alternative speedup. If the live run takes longer, extend the recording or clearly label a cut in waiting time. Never alter numerical results to match the storyboard.

## Recording steps

1. Open the README, the presentation and a terminal at the repository root. Complete dependency/model setup before recording.
2. Select an application/window region at 1280×720 or larger. Enable the microphone if narrating, and do a short sound/readability test.
3. Start recording, follow the storyboard, and run the real command. Keep all error/failure output visible if it occurs.
4. Stop the recorder and review the saved clip. Confirm readable command output, intact uncertainty caveats and no unrelated personal data.
5. Keep the recording outside Git by default. Publish only after review and explicit authorization.

The [spoken explanation](APPLICATION_RESPONSE.md) is a separate approximately 90-second narrative; rehearse and adjust pacing rather than assert an unmeasured exact duration.
