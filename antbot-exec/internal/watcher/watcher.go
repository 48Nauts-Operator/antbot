package watcher

import (
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	pb "github.com/48Nauts-Operator/antbot-exec/api/gen"
	"github.com/fsnotify/fsnotify"
)

// Watcher monitors directories for file changes with debounce.
type Watcher struct {
	mu       sync.Mutex
	fsw      *fsnotify.Watcher
	pending  map[string]*pendingEvent
	debounce time.Duration
	ignores  []string
	stopCh   chan struct{}
}

type pendingEvent struct {
	event *pb.FSEvent
	timer *time.Timer
}

// New creates a watcher with the given debounce duration.
func New(debounce time.Duration) (*Watcher, error) {
	fsw, err := fsnotify.NewWatcher()
	if err != nil {
		return nil, err
	}
	return &Watcher{
		fsw:      fsw,
		pending:  make(map[string]*pendingEvent),
		debounce: debounce,
		stopCh:   make(chan struct{}),
	}, nil
}

// Watch starts watching the given paths and sends stable events to the channel.
func (w *Watcher) Watch(paths []string, ignores []string, recursive bool, out chan<- *pb.FSEvent) error {
	w.ignores = ignores

	for _, p := range paths {
		expanded := expandPath(p)
		if recursive {
			if err := w.addRecursive(expanded); err != nil {
				return err
			}
		} else {
			if err := w.fsw.Add(expanded); err != nil {
				return err
			}
		}
	}

	go w.loop(out)
	return nil
}

// Stop stops the watcher.
func (w *Watcher) Stop() {
	close(w.stopCh)
	w.fsw.Close()
}

func (w *Watcher) loop(out chan<- *pb.FSEvent) {
	for {
		select {
		case <-w.stopCh:
			return
		case event, ok := <-w.fsw.Events:
			if !ok {
				return
			}
			w.handleFSEvent(event, out)
		case err, ok := <-w.fsw.Errors:
			if !ok {
				return
			}
			log.Printf("watcher error: %v", err)
		}
	}
}

func (w *Watcher) handleFSEvent(event fsnotify.Event, out chan<- *pb.FSEvent) {
	path := event.Name

	// Skip ignored patterns
	for _, pattern := range w.ignores {
		if matched, _ := filepath.Match(pattern, filepath.Base(path)); matched {
			return
		}
	}

	// Skip hidden files and temp files
	base := filepath.Base(path)
	if strings.HasPrefix(base, ".") || strings.HasSuffix(base, ".tmp") || strings.HasSuffix(base, ".crdownload") || strings.HasSuffix(base, ".part") {
		return
	}

	op := mapOp(event.Op)
	if op == pb.FSEventOp_FS_EVENT_OP_UNSPECIFIED {
		return
	}

	// For creates and writes, debounce to wait for file stability
	if op == pb.FSEventOp_FS_EVENT_OP_CREATE || op == pb.FSEventOp_FS_EVENT_OP_WRITE {
		w.debounceEvent(path, op, out)
		return
	}

	// Deletes and renames fire immediately
	out <- &pb.FSEvent{
		Path:        path,
		Op:          op,
		TimestampMs: time.Now().UnixMilli(),
	}
}

func (w *Watcher) debounceEvent(path string, op pb.FSEventOp, out chan<- *pb.FSEvent) {
	w.mu.Lock()
	defer w.mu.Unlock()

	if pe, exists := w.pending[path]; exists {
		pe.timer.Reset(w.debounce)
		return
	}

	evt := &pb.FSEvent{
		Path: path,
		Op:   op,
	}

	timer := time.AfterFunc(w.debounce, func() {
		w.mu.Lock()
		delete(w.pending, path)
		w.mu.Unlock()

		// Fill in file info now that the file is stable
		if info, err := os.Stat(path); err == nil {
			evt.SizeBytes = info.Size()
			evt.MimeType = probeMimeType(path)
		}
		evt.TimestampMs = time.Now().UnixMilli()

		out <- evt
	})

	w.pending[path] = &pendingEvent{event: evt, timer: timer}
}

func (w *Watcher) addRecursive(root string) error {
	return filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil // skip inaccessible dirs
		}
		if info.IsDir() {
			base := filepath.Base(path)
			if strings.HasPrefix(base, ".") && path != root {
				return filepath.SkipDir
			}
			return w.fsw.Add(path)
		}
		return nil
	})
}

func mapOp(op fsnotify.Op) pb.FSEventOp {
	switch {
	case op.Has(fsnotify.Create):
		return pb.FSEventOp_FS_EVENT_OP_CREATE
	case op.Has(fsnotify.Write):
		return pb.FSEventOp_FS_EVENT_OP_WRITE
	case op.Has(fsnotify.Remove):
		return pb.FSEventOp_FS_EVENT_OP_REMOVE
	case op.Has(fsnotify.Rename):
		return pb.FSEventOp_FS_EVENT_OP_RENAME
	default:
		return pb.FSEventOp_FS_EVENT_OP_UNSPECIFIED
	}
}

func probeMimeType(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return "application/octet-stream"
	}
	defer f.Close()

	buf := make([]byte, 512)
	n, err := f.Read(buf)
	if err != nil || n == 0 {
		return "application/octet-stream"
	}
	return http.DetectContentType(buf[:n])
}

func expandPath(p string) string {
	if strings.HasPrefix(p, "~/") {
		home, _ := os.UserHomeDir()
		return filepath.Join(home, p[2:])
	}
	return p
}
