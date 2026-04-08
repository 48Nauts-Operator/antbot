package health

import (
	"os"
)

// CheckMount verifies a filesystem path is accessible (NAS mount check).
func CheckMount(path string) bool {
	info, err := os.Stat(path)
	if err != nil {
		return false
	}
	return info.IsDir()
}

// DiskFreeBytes returns free bytes on the filesystem containing path.
// Returns 0 on error (cross-platform fallback).
func DiskFreeBytes(path string) uint64 {
	// Implemented via syscall in health_darwin.go / health_linux.go
	return diskFree(path)
}
