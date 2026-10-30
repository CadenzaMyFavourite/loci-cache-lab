use std::collections::VecDeque;

#[derive(Clone, Debug, Default)]
struct Slot {
    tokens: Vec<u32>,
    conversation: Option<String>,
    busy: bool,
    last_used: u64,
}

#[derive(Clone, Debug, serde::Serialize)]
pub struct Decision {
    pub slot: usize,
    pub reason: &'static str,
    pub predicted_prefix_tokens: usize,
    pub eviction_score: usize,
}

/// Routing metadata only; the inference engine validates all actual KV reuse.
pub struct Scheduler {
    slots: Vec<Slot>,
    history: VecDeque<String>,
    scope: String,
    clock: u64,
}

pub fn common_prefix(a: &[u32], b: &[u32]) -> usize {
    a.iter().zip(b).take_while(|(a, b)| a == b).count()
}

impl Scheduler {
    pub fn new(count: usize, scope: String) -> Self {
        assert!(count > 0);
        Self {
            slots: vec![Slot::default(); count],
            history: VecDeque::new(),
            scope,
            clock: 0,
        }
    }

    pub fn reset(&mut self, scope: String) {
        self.slots.fill(Slot::default());
        self.history.clear();
        self.scope = scope;
        self.clock = 0;
    }

    fn score(&self, index: usize) -> usize {
        let slot = &self.slots[index];
        slot.tokens.len()
            * self
                .history
                .iter()
                .filter(|id| Some(*id) == slot.conversation.as_ref())
                .count()
    }

    pub fn reserve(&mut self, conversation: &str, tokens: &[u32], scope: &str) -> Option<Decision> {
        // A scope change is safe only between generations. The caller never changes
        // model/template configuration while leases are live.
        if self.scope != scope {
            if self.slots.iter().any(|s| s.busy) {
                return None;
            }
            self.reset(scope.to_owned());
        }
        let idle: Vec<usize> = (0..self.slots.len())
            .filter(|&i| !self.slots[i].busy)
            .collect();
        let best = idle
            .iter()
            .copied()
            .filter_map(|i| {
                let prefix = common_prefix(&self.slots[i].tokens, tokens);
                if !tokens.is_empty() && prefix as f64 / tokens.len() as f64 > 0.10 {
                    Some((i, prefix))
                } else {
                    None
                }
            })
            .max_by_key(|&(i, prefix)| (prefix, std::cmp::Reverse(i)));
        let (slot, reason, prefix) = if let Some((i, prefix)) = best {
            (i, "prefix", prefix)
        } else if let Some(i) = idle
            .iter()
            .copied()
            .find(|&i| self.slots[i].tokens.is_empty())
        {
            (i, "empty", 0)
        } else {
            let i = idle
                .into_iter()
                .min_by_key(|&i| (self.score(i), self.slots[i].last_used, i))?;
            (i, "retention", common_prefix(&self.slots[i].tokens, tokens))
        };
        let decision = Decision {
            slot,
            reason,
            predicted_prefix_tokens: prefix,
            eviction_score: self.score(slot),
        };
        self.slots[slot].busy = true;
        self.clock += 1;
        self.slots[slot].last_used = self.clock;
        self.history.push_back(conversation.to_owned());
        if self.history.len() > 32 {
            self.history.pop_front();
        }
        Some(decision)
    }

    pub fn finish(&mut self, slot: usize, conversation: String, tokens: Vec<u32>) {
        assert!(self.slots[slot].busy);
        self.slots[slot].tokens = tokens;
        self.slots[slot].conversation = Some(conversation);
        self.slots[slot].busy = false;
    }

    pub fn invalidate(&mut self, slot: usize) {
        self.slots[slot] = Slot::default();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn cached(s: &mut Scheduler, id: &str, tokens: Vec<u32>) -> usize {
        let d = s.reserve(id, &tokens, "scope").unwrap();
        s.finish(d.slot, id.into(), tokens);
        d.slot
    }
    #[test]
    fn prefix_edit_and_busy_slots() {
        let mut s = Scheduler::new(2, "scope".into());
        cached(&mut s, "a", vec![1, 2, 3, 4]);
        cached(&mut s, "b", vec![8, 9]);
        let d = s.reserve("a", &[1, 2, 7], "scope").unwrap();
        assert_eq!((d.slot, d.predicted_prefix_tokens), (0, 2));
        let e = s.reserve("a", &[1, 2, 7], "scope").unwrap();
        assert_eq!(e.slot, 1);
        assert!(s.reserve("c", &[3], "scope").is_none());
        s.invalidate(d.slot);
        assert_eq!(s.reserve("c", &[3], "scope").unwrap().reason, "empty");
    }
    #[test]
    fn protects_frequently_reused_expensive_prefix() {
        let mut s = Scheduler::new(2, "scope".into());
        cached(&mut s, "a", vec![1; 100]);
        cached(&mut s, "b", vec![2; 20]);
        for _ in 0..4 {
            cached(&mut s, "a", vec![1; 100]);
        }
        // Make B more recent. Retention must still evict B rather than A.
        cached(&mut s, "b", vec![2; 20]);
        assert_eq!(s.reserve("c", &[3; 30], "scope").unwrap().slot, 1);
    }
    #[test]
    fn invalidates_template_model_and_restart_state() {
        let mut s = Scheduler::new(2, "scope".into());
        cached(&mut s, "a", vec![1; 10]);
        assert_eq!(
            s.reserve("a", &[1; 10], "new-template").unwrap().reason,
            "empty"
        );
        s.reset("scope".into());
        assert_eq!(s.reserve("a", &[1; 10], "scope").unwrap().reason, "empty");
    }
    #[test]
    fn threshold_ties_and_system_change() {
        let mut s = Scheduler::new(2, "scope".into());
        cached(&mut s, "a", vec![1; 10]);
        cached(&mut s, "b", vec![2; 10]);
        assert_eq!(s.reserve("c", &[3; 10], "scope").unwrap().slot, 0);
        assert_eq!(common_prefix(&[1, 2, 3], &[9, 2, 3]), 0);
        assert_eq!(common_prefix(&[], &[9]), 0);
    }
    #[test]
    fn history_is_bounded() {
        let mut s = Scheduler::new(1, "scope".into());
        for i in 0..40 {
            cached(&mut s, &i.to_string(), vec![i; 10]);
        }
        assert_eq!(s.history.len(), 32);
        assert_eq!(s.history.front().unwrap(), "8");
    }
}
