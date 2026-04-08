package queue

import (
	"encoding/json"
	"os"
	"sync"

	pb "github.com/48Nauts-Operator/antbot-exec/api/gen"
)

// Queue buffers FSEvents to a JSONL file when the Python brain is unreachable.
type Queue struct {
	mu        sync.Mutex
	path      string
	events    []*pb.FSEvent
	totalSeen int32
}

// New creates a queue backed by the given file path.
func New(path string) *Queue {
	q := &Queue{path: path}
	q.load() // restore from disk if exists
	return q
}

// Push adds an event to the queue and persists to disk.
func (q *Queue) Push(event *pb.FSEvent) {
	q.mu.Lock()
	defer q.mu.Unlock()

	q.events = append(q.events, event)
	q.totalSeen++
	q.save()
}

// Drain returns up to maxEvents from the queue and removes them.
// If maxEvents <= 0, drains all.
func (q *Queue) Drain(maxEvents int32) []*pb.FSEvent {
	q.mu.Lock()
	defer q.mu.Unlock()

	if maxEvents <= 0 || int(maxEvents) >= len(q.events) {
		result := q.events
		q.events = nil
		q.save()
		return result
	}

	result := q.events[:maxEvents]
	q.events = q.events[maxEvents:]
	q.save()
	return result
}

// Len returns the number of buffered events.
func (q *Queue) Len() int32 {
	q.mu.Lock()
	defer q.mu.Unlock()
	return int32(len(q.events))
}

// TotalSeen returns total events seen since creation.
func (q *Queue) TotalSeen() int32 {
	q.mu.Lock()
	defer q.mu.Unlock()
	return q.totalSeen
}

// OldestMs returns the timestamp of the oldest buffered event, or 0 if empty.
func (q *Queue) OldestMs() int64 {
	q.mu.Lock()
	defer q.mu.Unlock()
	if len(q.events) == 0 {
		return 0
	}
	return q.events[0].TimestampMs
}

type serialized struct {
	Events    []*pb.FSEvent `json:"events"`
	TotalSeen int32         `json:"total_seen"`
}

func (q *Queue) save() {
	data, err := json.Marshal(serialized{Events: q.events, TotalSeen: q.totalSeen})
	if err != nil {
		return
	}
	os.WriteFile(q.path, data, 0644)
}

func (q *Queue) load() {
	data, err := os.ReadFile(q.path)
	if err != nil {
		return
	}
	var s serialized
	if err := json.Unmarshal(data, &s); err != nil {
		return
	}
	q.events = s.Events
	q.totalSeen = s.TotalSeen
}
