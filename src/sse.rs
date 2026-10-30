use anyhow::{Result, bail};

/// Byte buffering preserves UTF-8 characters split across network chunks.
#[derive(Default)]
pub struct Decoder {
    pending: Vec<u8>,
    data: Vec<String>,
}
impl Decoder {
    pub fn push(&mut self, bytes: &[u8]) -> Result<Vec<serde_json::Value>> {
        self.pending.extend_from_slice(bytes);
        if self.pending.len() > 16 * 1024 * 1024 {
            bail!("SSE event exceeded 16 MiB");
        }
        let mut events = Vec::new();
        while let Some(end) = self.pending.iter().position(|&b| b == b'\n') {
            let line: Vec<u8> = self.pending.drain(..=end).collect();
            let line = std::str::from_utf8(&line)?.trim_end_matches(['\r', '\n']);
            if line.is_empty() {
                if !self.data.is_empty() {
                    let payload = self.data.join("\n");
                    self.data.clear();
                    if payload != "[DONE]" {
                        events.push(serde_json::from_str(&payload)?);
                    }
                }
            } else if let Some(data) = line.strip_prefix("data:") {
                self.data
                    .push(data.strip_prefix(' ').unwrap_or(data).to_owned());
            }
        }
        Ok(events)
    }
    pub fn finish(&mut self) -> Result<()> {
        if !self.pending.is_empty() || !self.data.is_empty() {
            bail!("incomplete SSE stream");
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn split_utf8_crlf_and_empty_initial_events() {
        let bytes =
            "data: {\"content\":\"\"}\r\n\r\ndata: {\"content\":\"你\"}\n\ndata: [DONE]\n\n"
                .as_bytes();
        let mut decoder = Decoder::default();
        let mut events = vec![];
        for byte in bytes {
            events.extend(decoder.push(&[*byte]).unwrap());
        }
        decoder.finish().unwrap();
        assert_eq!(events.len(), 2);
        assert_eq!(events[1]["content"], "你");
    }
    #[test]
    fn detects_truncation_and_bad_json() {
        let mut d = Decoder::default();
        d.push(b"data: {}").unwrap();
        assert!(d.finish().is_err());
        assert!(Decoder::default().push(b"data: nope\n\n").is_err());
    }
}
