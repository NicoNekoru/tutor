use serde::{Deserialize, Deserializer, Serialize, Serializer};
use sha2::{Digest, Sha256};
use std::fmt;

use crate::error::{Error, Result};

/// A SHA-256 content hash. The fundamental identity type.
/// Two objects with the same bytes produce the same Hash.
#[derive(Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Hash([u8; 32]);

impl Hash {
    /// Compute the SHA-256 hash of raw bytes.
    pub fn compute(data: &[u8]) -> Self {
        let mut hasher = Sha256::new();
        hasher.update(data);
        let result = hasher.finalize();
        let mut bytes = [0u8; 32];
        bytes.copy_from_slice(&result);
        Hash(bytes)
    }

    /// Create a Hash from a 32-byte array.
    pub fn from_bytes(bytes: [u8; 32]) -> Self {
        Hash(bytes)
    }

    /// The raw 32 bytes.
    pub fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }

    /// Full 64-character lowercase hex string.
    pub fn to_hex(&self) -> String {
        let mut s = String::with_capacity(64);
        for byte in &self.0 {
            s.push_str(&format!("{:02x}", byte));
        }
        s
    }

    /// Parse from a 64-character hex string.
    pub fn from_hex(hex: &str) -> Result<Self> {
        if hex.len() != 64 {
            return Err(Error::InvalidHash(format!(
                "expected 64 hex chars, got {}",
                hex.len()
            )));
        }
        let mut bytes = [0u8; 32];
        for i in 0..32 {
            bytes[i] = u8::from_str_radix(&hex[i * 2..i * 2 + 2], 16)
                .map_err(|_| Error::InvalidHash(format!("invalid hex at position {}", i * 2)))?;
        }
        Ok(Hash(bytes))
    }

    /// First 2 hex characters, used for filesystem sharding.
    pub fn shard_prefix(&self) -> String {
        format!("{:02x}", self.0[0])
    }

    /// Short display: first 8 hex characters.
    pub fn short(&self) -> String {
        self.to_hex()[..8].to_string()
    }

    /// A zeroed hash, useful as a sentinel/null value.
    pub fn zero() -> Self {
        Hash([0u8; 32])
    }
}

impl fmt::Display for Hash {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.to_hex())
    }
}

impl fmt::Debug for Hash {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Hash({})", self.short())
    }
}

/// Serialize as hex string for human-readable formats, raw bytes for binary.
impl Serialize for Hash {
    fn serialize<S: Serializer>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error> {
        if serializer.is_human_readable() {
            serializer.serialize_str(&self.to_hex())
        } else {
            serializer.serialize_bytes(&self.0)
        }
    }
}

impl<'de> Deserialize<'de> for Hash {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        if deserializer.is_human_readable() {
            let s = String::deserialize(deserializer)?;
            Hash::from_hex(&s).map_err(serde::de::Error::custom)
        } else {
            let bytes = <Vec<u8>>::deserialize(deserializer)?;
            if bytes.len() != 32 {
                return Err(serde::de::Error::custom(format!(
                    "expected 32 bytes, got {}",
                    bytes.len()
                )));
            }
            let mut arr = [0u8; 32];
            arr.copy_from_slice(&bytes);
            Ok(Hash(arr))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_deterministic_hashing() {
        let data = b"hello world";
        let h1 = Hash::compute(data);
        let h2 = Hash::compute(data);
        assert_eq!(h1, h2, "Same input must produce same hash");
    }

    #[test]
    fn test_different_inputs_different_hashes() {
        let h1 = Hash::compute(b"hello");
        let h2 = Hash::compute(b"world");
        assert_ne!(h1, h2);
    }

    #[test]
    fn test_known_sha256() {
        // SHA-256 of empty string is well-known
        let h = Hash::compute(b"");
        assert_eq!(
            h.to_hex(),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }

    #[test]
    fn test_hex_roundtrip() {
        let h = Hash::compute(b"test data");
        let hex = h.to_hex();
        let h2 = Hash::from_hex(&hex).unwrap();
        assert_eq!(h, h2);
    }

    #[test]
    fn test_shard_prefix() {
        let h = Hash::compute(b"test");
        let prefix = h.shard_prefix();
        assert_eq!(prefix.len(), 2);
        assert_eq!(&h.to_hex()[..2], &prefix);
    }

    #[test]
    fn test_invalid_hex() {
        assert!(Hash::from_hex("too_short").is_err());
        assert!(Hash::from_hex(&"zz".repeat(32)).is_err());
    }

    #[test]
    fn test_serde_json_roundtrip() {
        let h = Hash::compute(b"serde test");
        let json = serde_json::to_string(&h).unwrap();
        let h2: Hash = serde_json::from_str(&json).unwrap();
        assert_eq!(h, h2);
        // JSON should be a hex string
        assert!(json.contains(&h.to_hex()));
    }

    #[test]
    fn test_serde_bincode_roundtrip() {
        let h = Hash::compute(b"bincode test");
        let bytes = bincode::serialize(&h).unwrap();
        let h2: Hash = bincode::deserialize(&bytes).unwrap();
        assert_eq!(h, h2);
    }

    #[test]
    fn test_ordering() {
        let h1 = Hash::from_bytes([0u8; 32]);
        let h2 = Hash::from_bytes([1u8; 32]);
        assert!(h1 < h2);
    }
}
