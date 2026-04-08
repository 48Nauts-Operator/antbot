package git

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// RepoStatus represents the git status of a repository.
type RepoStatus struct {
	Path         string    `json:"path"`
	Name         string    `json:"name"`
	Branch       string    `json:"branch"`
	Remote       string    `json:"remote"`
	DirtyFiles   int       `json:"dirty_files"`
	UntrackedFiles int    `json:"untracked_files"`
	AheadBy      int       `json:"ahead_by"`
	LastCommit   time.Time `json:"last_commit"`
	LastMessage  string    `json:"last_message"`
	HasGit       bool      `json:"has_git"`
}

// Status returns the git status of a repository.
func Status(repoPath string) (*RepoStatus, error) {
	s := &RepoStatus{
		Path: repoPath,
		Name: filepath.Base(repoPath),
	}

	// Check if .git exists
	if _, err := os.Stat(filepath.Join(repoPath, ".git")); err != nil {
		s.HasGit = false
		return s, nil
	}
	s.HasGit = true

	// Branch
	if out, err := gitCmd(repoPath, "rev-parse", "--abbrev-ref", "HEAD"); err == nil {
		s.Branch = strings.TrimSpace(out)
	}

	// Remote
	if out, err := gitCmd(repoPath, "remote", "get-url", "origin"); err == nil {
		s.Remote = strings.TrimSpace(out)
	}

	// Dirty files (modified + staged)
	if out, err := gitCmd(repoPath, "status", "--porcelain"); err == nil {
		lines := strings.Split(strings.TrimSpace(out), "\n")
		for _, l := range lines {
			l = strings.TrimSpace(l)
			if l == "" {
				continue
			}
			if strings.HasPrefix(l, "??") {
				s.UntrackedFiles++
			} else {
				s.DirtyFiles++
			}
		}
	}

	// Ahead count
	if out, err := gitCmd(repoPath, "rev-list", "--count", "@{u}..HEAD"); err == nil {
		fmt.Sscanf(strings.TrimSpace(out), "%d", &s.AheadBy)
	}

	// Last commit
	if out, err := gitCmd(repoPath, "log", "-1", "--format=%aI\n%s"); err == nil {
		parts := strings.SplitN(strings.TrimSpace(out), "\n", 2)
		if len(parts) >= 1 {
			s.LastCommit, _ = time.Parse(time.RFC3339, parts[0])
		}
		if len(parts) >= 2 {
			s.LastMessage = parts[1]
		}
	}

	return s, nil
}

// Bundle creates a git bundle file containing all refs.
func Bundle(repoPath, outputPath string) error {
	if _, err := os.Stat(filepath.Join(repoPath, ".git")); err != nil {
		return fmt.Errorf("not a git repository: %s", repoPath)
	}

	// Ensure output directory exists
	if err := os.MkdirAll(filepath.Dir(outputPath), 0755); err != nil {
		return err
	}

	_, err := gitCmd(repoPath, "bundle", "create", outputPath, "--all")
	return err
}

func gitCmd(dir string, args ...string) (string, error) {
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	out, err := cmd.Output()
	return string(out), err
}
