use std::fs;
use std::path::{Path, PathBuf};

use crate::error::{Error, Result};
use crate::hash::Hash;

/// A named pointer to a Hash. The only mutable state in the workspace.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Ref {
    pub name: String,
    pub target: Hash,
}

/// Manages the refs/ directory.
///
/// Ref names map to file paths: "student/mastery" → refs/student/mastery
/// File content is the 64-char hex hash + newline.
///
/// All writes use the tmp-then-rename pattern for atomicity.
pub struct RefStore {
    /// Path to .rlm/refs/
    refs_dir: PathBuf,
    /// Path to .rlm/tmp/
    tmp_dir: PathBuf,
}

impl RefStore {
    pub fn open(rlm_root: &Path) -> Result<Self> {
        let refs_dir = rlm_root.join("refs");
        let tmp_dir = rlm_root.join("tmp");
        Ok(RefStore { refs_dir, tmp_dir })
    }

    pub fn init_dirs(&self) -> Result<()> {
        fs::create_dir_all(&self.refs_dir).map_err(|e| Error::io(e, &self.refs_dir))?;
        fs::create_dir_all(&self.tmp_dir).map_err(|e| Error::io(e, &self.tmp_dir))?;
        Ok(())
    }

    /// Read a ref by name. Returns None if the ref doesn't exist.
    pub fn read(&self, name: &str) -> Result<Option<Hash>> {
        let path = self.ref_path(name);
        let data = match fs::read_to_string(&path) {
            Ok(d) => d,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(Error::io(e, &path)),
        };
        let hex = data.trim();
        let hash = Hash::from_hex(hex)?;
        Ok(Some(hash))
    }

    /// Write (create or overwrite) a ref. Atomic via tmp+rename.
    pub fn write(&self, name: &str, target: &Hash) -> Result<()> {
        let path = self.ref_path(name);

        // Ensure parent directories exist.
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| Error::io(e, parent))?;
        }

        // Write to tmp, then rename.
        let tmp_path = self.tmp_dir.join(format!("ref_{}", target.short()));
        let content = format!("{}\n", target.to_hex());
        fs::write(&tmp_path, content.as_bytes()).map_err(|e| Error::io(e, &tmp_path))?;
        fs::rename(&tmp_path, &path).map_err(|e| Error::io(e, &path))?;

        Ok(())
    }

    /// Delete a ref. Returns true if it existed.
    pub fn delete(&self, name: &str) -> Result<bool> {
        let path = self.ref_path(name);
        match fs::remove_file(&path) {
            Ok(()) => Ok(true),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
            Err(e) => Err(Error::io(e, &path)),
        }
    }

    /// Compare-and-swap: only update if the current value matches `expected`.
    /// Returns Ok(()) on success, Err(RefConflict) if the ref has changed.
    /// If the ref doesn't exist and `expected` is Hash::zero(), creates it.
    pub fn cas(&self, name: &str, expected: &Hash, new: &Hash) -> Result<()> {
        let current = self.read(name)?;
        let current_hash = current.unwrap_or_else(Hash::zero);

        if current_hash != *expected {
            return Err(Error::RefConflict {
                name: name.to_string(),
                expected: expected.short(),
                actual: current_hash.short(),
            });
        }

        self.write(name, new)
    }

    /// List all refs matching a prefix.
    /// E.g., list("student/") returns all refs under student/.
    /// list("") returns all refs.
    pub fn list(&self, prefix: &str) -> Result<Vec<Ref>> {
        let search_dir = if prefix.is_empty() {
            self.refs_dir.clone()
        } else {
            self.refs_dir.join(prefix)
        };
        let mut results = Vec::new();
        self.list_recursive(&search_dir, &mut results)?;
        Ok(results)
    }

    fn list_recursive(&self, dir: &Path, results: &mut Vec<Ref>) -> Result<()> {
        let entries = match fs::read_dir(dir) {
            Ok(e) => e,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
            Err(e) => return Err(Error::io(e, dir)),
        };
        for entry in entries {
            let entry = entry.map_err(|e| Error::io(e, dir))?;
            let path = entry.path();
            if path.is_dir() {
                self.list_recursive(&path, results)?;
            } else {
                // Derive the ref name from the path relative to refs_dir.
                if let Ok(rel) = path.strip_prefix(&self.refs_dir) {
                    let name = rel.to_string_lossy().replace('\\', "/");
                    if let Ok(Some(hash)) = self.read(&name) {
                        results.push(Ref {
                            name,
                            target: hash,
                        });
                    }
                }
            }
        }
        Ok(())
    }

    fn ref_path(&self, name: &str) -> PathBuf {
        self.refs_dir.join(name)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn setup() -> (TempDir, RefStore) {
        let dir = TempDir::new().unwrap();
        let rlm_root = dir.path().join(".rlm");
        fs::create_dir_all(&rlm_root).unwrap();
        let store = RefStore::open(&rlm_root).unwrap();
        store.init_dirs().unwrap();
        (dir, store)
    }

    #[test]
    fn test_write_read() {
        let (_dir, store) = setup();
        let hash = Hash::compute(b"target");
        store.write("HEAD", &hash).unwrap();
        let read = store.read("HEAD").unwrap();
        assert_eq!(read, Some(hash));
    }

    #[test]
    fn test_read_nonexistent() {
        let (_dir, store) = setup();
        assert_eq!(store.read("nope").unwrap(), None);
    }

    #[test]
    fn test_nested_ref() {
        let (_dir, store) = setup();
        let hash = Hash::compute(b"student model");
        store.write("student/mastery", &hash).unwrap();
        let read = store.read("student/mastery").unwrap();
        assert_eq!(read, Some(hash));
    }

    #[test]
    fn test_overwrite() {
        let (_dir, store) = setup();
        let h1 = Hash::compute(b"v1");
        let h2 = Hash::compute(b"v2");
        store.write("HEAD", &h1).unwrap();
        store.write("HEAD", &h2).unwrap();
        assert_eq!(store.read("HEAD").unwrap(), Some(h2));
    }

    #[test]
    fn test_delete() {
        let (_dir, store) = setup();
        let hash = Hash::compute(b"target");
        store.write("temp", &hash).unwrap();
        assert!(store.delete("temp").unwrap());
        assert_eq!(store.read("temp").unwrap(), None);
        assert!(!store.delete("temp").unwrap()); // already gone
    }

    #[test]
    fn test_cas_success() {
        let (_dir, store) = setup();
        let h1 = Hash::compute(b"v1");
        let h2 = Hash::compute(b"v2");
        store.write("HEAD", &h1).unwrap();
        store.cas("HEAD", &h1, &h2).unwrap();
        assert_eq!(store.read("HEAD").unwrap(), Some(h2));
    }

    #[test]
    fn test_cas_conflict() {
        let (_dir, store) = setup();
        let h1 = Hash::compute(b"v1");
        let h2 = Hash::compute(b"v2");
        let h_wrong = Hash::compute(b"wrong");
        store.write("HEAD", &h1).unwrap();
        let result = store.cas("HEAD", &h_wrong, &h2);
        assert!(result.is_err());
        // Value should be unchanged.
        assert_eq!(store.read("HEAD").unwrap(), Some(h1));
    }

    #[test]
    fn test_cas_create_from_zero() {
        let (_dir, store) = setup();
        let h = Hash::compute(b"new");
        // CAS with expected=zero on a non-existent ref should create it.
        store.cas("new_ref", &Hash::zero(), &h).unwrap();
        assert_eq!(store.read("new_ref").unwrap(), Some(h));
    }

    #[test]
    fn test_cas_create_conflict() {
        let (_dir, store) = setup();
        let h1 = Hash::compute(b"existing");
        let h2 = Hash::compute(b"new");
        store.write("ref", &h1).unwrap();
        // CAS from zero should fail if ref already exists.
        let result = store.cas("ref", &Hash::zero(), &h2);
        assert!(result.is_err());
    }

    #[test]
    fn test_list_all() {
        let (_dir, store) = setup();
        store.write("HEAD", &Hash::compute(b"a")).unwrap();
        store.write("student/mastery", &Hash::compute(b"b")).unwrap();
        store.write("student/session", &Hash::compute(b"c")).unwrap();
        store.write("course/structure", &Hash::compute(b"d")).unwrap();

        let all = store.list("").unwrap();
        assert_eq!(all.len(), 4);
    }

    #[test]
    fn test_list_prefix() {
        let (_dir, store) = setup();
        store.write("HEAD", &Hash::compute(b"a")).unwrap();
        store.write("student/mastery", &Hash::compute(b"b")).unwrap();
        store.write("student/session", &Hash::compute(b"c")).unwrap();
        store.write("course/structure", &Hash::compute(b"d")).unwrap();

        let student_refs = store.list("student").unwrap();
        assert_eq!(student_refs.len(), 2);
        for r in &student_refs {
            assert!(r.name.starts_with("student/"));
        }
    }
}
