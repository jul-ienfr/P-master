use std::fmt::{self, Debug, Formatter};
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering::Relaxed};

#[cfg(feature = "bincode")]
use bincode::{Decode, Encode};

#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
pub(crate) struct AtomicF32(AtomicU32);

#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
pub(crate) struct AtomicF64(AtomicU64);

impl AtomicF32 {
    pub(crate) fn new(v: f32) -> Self {
        Self(AtomicU32::new(v.to_bits()))
    }

    pub(crate) fn load(&self) -> f32 {
        f32::from_bits(self.0.load(Relaxed))
    }

    pub(crate) fn store(&self, v: f32) {
        self.0.store(v.to_bits(), Relaxed);
    }
}

impl AtomicF64 {
    pub(crate) fn new(v: f64) -> Self {
        Self(AtomicU64::new(v.to_bits()))
    }

    pub(crate) fn load(&self) -> f64 {
        f64::from_bits(self.0.load(Relaxed))
    }

    pub(crate) fn store(&self, v: f64) {
        self.0.store(v.to_bits(), Relaxed);
    }

    pub(crate) fn add(&self, v: f64) {
        // Boucle CAS explicite : `fetch_update` est déprécié au profit de
        // `try_update` (non disponible sur la toolchain épinglée).
        let mut observed = self.0.load(Relaxed);
        loop {
            let updated = (f64::from_bits(observed) + v).to_bits();
            match self
                .0
                .compare_exchange_weak(observed, updated, Relaxed, Relaxed)
            {
                Ok(_) => return,
                Err(actual) => observed = actual,
            }
        }
    }
}

impl Debug for AtomicF32 {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        self.load().fmt(f)
    }
}

impl Debug for AtomicF64 {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        self.load().fmt(f)
    }
}
