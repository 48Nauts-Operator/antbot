package mover

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// Move moves a file from src to dst with optional checksum verification.
// Returns (size, checksum, error). Fails if dst exists and overwrite is false.
func Move(src, dst string, overwrite, dryRun bool) (int64, string, error) {
	srcInfo, err := os.Stat(src)
	if err != nil {
		return 0, "", fmt.Errorf("source not found: %w", err)
	}
	if srcInfo.IsDir() {
		return 0, "", fmt.Errorf("source is a directory, not a file")
	}

	// Check destination
	if !overwrite {
		if _, err := os.Stat(dst); err == nil {
			return 0, "", fmt.Errorf("destination already exists: %s", dst)
		}
	}

	if dryRun {
		return srcInfo.Size(), "", nil
	}

	// Ensure destination directory exists
	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return 0, "", fmt.Errorf("failed to create destination directory: %w", err)
	}

	// Copy file to destination
	size, checksum, err := copyFile(src, dst)
	if err != nil {
		// Clean up partial copy
		os.Remove(dst)
		return 0, "", err
	}

	// Verify checksum
	dstChecksum, err := hashFile(dst)
	if err != nil {
		os.Remove(dst)
		return 0, "", fmt.Errorf("checksum verification failed: %w", err)
	}
	if checksum != dstChecksum {
		os.Remove(dst)
		return 0, "", fmt.Errorf("checksum mismatch: src=%s dst=%s", checksum, dstChecksum)
	}

	// Remove source after successful copy + verify
	if err := os.Remove(src); err != nil {
		return size, checksum, fmt.Errorf("copied successfully but failed to remove source: %w", err)
	}

	return size, checksum, nil
}

// Copy copies a file from src to dst with checksum verification.
// Fails if dst exists and overwrite is false.
func Copy(src, dst string, overwrite, dryRun bool) (int64, string, error) {
	srcInfo, err := os.Stat(src)
	if err != nil {
		return 0, "", fmt.Errorf("source not found: %w", err)
	}
	if srcInfo.IsDir() {
		return 0, "", fmt.Errorf("source is a directory, not a file")
	}

	if !overwrite {
		if _, err := os.Stat(dst); err == nil {
			return 0, "", fmt.Errorf("destination already exists: %s", dst)
		}
	}

	if dryRun {
		return srcInfo.Size(), "", nil
	}

	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return 0, "", fmt.Errorf("failed to create destination directory: %w", err)
	}

	size, checksum, err := copyFile(src, dst)
	if err != nil {
		os.Remove(dst)
		return 0, "", err
	}

	// Verify
	dstChecksum, err := hashFile(dst)
	if err != nil {
		os.Remove(dst)
		return 0, "", fmt.Errorf("checksum verification failed: %w", err)
	}
	if checksum != dstChecksum {
		os.Remove(dst)
		return 0, "", fmt.Errorf("checksum mismatch: src=%s dst=%s", checksum, dstChecksum)
	}

	return size, checksum, nil
}

func copyFile(src, dst string) (int64, string, error) {
	in, err := os.Open(src)
	if err != nil {
		return 0, "", err
	}
	defer in.Close()

	out, err := os.Create(dst)
	if err != nil {
		return 0, "", err
	}
	defer out.Close()

	h := sha256.New()
	w := io.MultiWriter(out, h)

	size, err := io.Copy(w, in)
	if err != nil {
		return 0, "", err
	}

	checksum := hex.EncodeToString(h.Sum(nil))

	// Preserve permissions
	if info, err := os.Stat(src); err == nil {
		os.Chmod(dst, info.Mode())
	}

	return size, checksum, nil
}

func hashFile(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()

	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
