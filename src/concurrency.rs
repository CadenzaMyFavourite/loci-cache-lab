//! Phase 2 controls: original frequency policy stays in `scheduler` unchanged.
use crate::scheduler::{Decision, Scheduler, common_prefix};

#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize, clap::ValueEnum)]
#[serde(rename_all = "snake_case")]
pub enum Arm {
    Stock,
    Fifo,
    Lru,
    Custom,
    /// Concurrent fallback: retain FIFO admission and let the engine choose.
    Corrected,
}
impl Arm {
    pub fn explicit(self) -> bool {
        matches!(self, Self::Lru | Self::Custom)
    }
    pub fn gated(self) -> bool {
        self != Self::Stock
    }
}

/// Explicit leases are useful only in the sequential corrected mode: engine
/// availability can change between HTTP dispatch and native task admission.
pub fn corrected_uses_explicit_slots(concurrency: usize) -> bool {
    concurrency == 1
}

#[derive(Default, Clone)]
struct Slot {
    tokens: Vec<u32>,
    busy: bool,
    last_used: u64,
}
pub struct Routing {
    legacy: Scheduler,
    slots: Vec<Slot>,
    clock: u64,
    scope: String,
}
impl Routing {
    pub fn new(scope: String) -> Self {
        Self {
            legacy: Scheduler::new(2, scope.clone()),
            slots: vec![Slot::default(); 2],
            clock: 0,
            scope,
        }
    }
    pub fn busy(&self) -> usize {
        self.slots.iter().filter(|s| s.busy).count()
    }
    pub fn reserve(&mut self, arm: Arm, id: &str, tokens: &[u32]) -> Option<Decision> {
        let decision = if arm == Arm::Custom {
            self.legacy.reserve(id, tokens, &self.scope)?
        } else {
            let idle: Vec<_> = (0..2).filter(|&i| !self.slots[i].busy).collect();
            let best = idle
                .iter()
                .copied()
                .map(|i| (i, common_prefix(&self.slots[i].tokens, tokens)))
                .filter(|&(_, n)| !tokens.is_empty() && n as f64 / tokens.len() as f64 > 0.10)
                .max_by_key(|&(i, n)| (n, std::cmp::Reverse(i)));
            let (slot, reason, prefix) = if let Some((i, n)) = best {
                (i, "prefix", n)
            } else if let Some(i) = idle
                .iter()
                .copied()
                .find(|&i| self.slots[i].tokens.is_empty())
            {
                (i, "empty", 0)
            } else {
                let i = idle
                    .into_iter()
                    .min_by_key(|&i| (self.slots[i].last_used, i))?;
                (i, "lru", common_prefix(&self.slots[i].tokens, tokens))
            };
            Decision {
                slot,
                reason,
                predicted_prefix_tokens: prefix,
                eviction_score: 0,
            }
        };
        assert!(!self.slots[decision.slot].busy);
        self.clock += 1;
        self.slots[decision.slot].busy = true;
        self.slots[decision.slot].last_used = self.clock;
        Some(decision)
    }
    pub fn finish(&mut self, arm: Arm, slot: usize, id: String, tokens: Vec<u32>) {
        assert!(self.slots[slot].busy);
        if arm == Arm::Custom {
            self.legacy.finish(slot, id, tokens.clone());
        }
        self.slots[slot].tokens = tokens;
        self.slots[slot].busy = false;
    }
    pub fn invalidate(&mut self, slot: usize) {
        self.slots[slot] = Slot::default();
        self.legacy.invalidate(slot);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn concurrent_fallback_delegates_live_slot_choice_but_keeps_fifo() {
        assert!(corrected_uses_explicit_slots(1));
        assert!(!corrected_uses_explicit_slots(2));
        assert!(!corrected_uses_explicit_slots(8));
        assert!(!Arm::Corrected.explicit());
        assert!(Arm::Corrected.gated());
        assert!(Arm::Custom.explicit());
    }
    #[test]
    fn lru_control_has_same_prefix_rule_but_no_frequency_protection() {
        let mut a = Routing::new("scope".into());
        for (id, tokens) in [
            ("A", vec![1; 100]),
            ("B", vec![2; 20]),
            ("A", vec![1; 100]),
            ("B", vec![2; 20]),
        ] {
            let d = a.reserve(Arm::Lru, id, &tokens).unwrap();
            a.finish(Arm::Lru, d.slot, id.into(), tokens);
        }
        assert_eq!(a.reserve(Arm::Lru, "C", &[3; 30]).unwrap().slot, 0);
    }
    #[test]
    fn cancellation_invalidates_and_never_double_reserves() {
        for arm in [Arm::Lru, Arm::Custom] {
            let mut a = Routing::new("s".into());
            let d = a.reserve(arm, "A", &[1; 10]).unwrap();
            let e = a.reserve(arm, "B", &[2; 10]).unwrap();
            assert_ne!(d.slot, e.slot);
            assert!(a.reserve(arm, "C", &[3; 10]).is_none());
            a.invalidate(d.slot);
            let f = a.reserve(arm, "C", &[3; 10]).unwrap();
            assert_eq!(f.slot, d.slot);
            assert_eq!(f.reason, "empty");
        }
    }
}
