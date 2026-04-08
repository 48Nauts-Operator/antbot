package server

import (
	"context"
	"time"

	pb "github.com/48Nauts-Operator/antbot-exec/api/gen"
	"github.com/48Nauts-Operator/antbot-exec/internal/health"
	"github.com/48Nauts-Operator/antbot-exec/internal/manifest"
	"github.com/48Nauts-Operator/antbot-exec/internal/mover"
	"github.com/48Nauts-Operator/antbot-exec/internal/queue"
	"github.com/48Nauts-Operator/antbot-exec/internal/watcher"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// Server implements all antbot-exec gRPC services.
type Server struct {
	pb.UnimplementedHealthServer
	pb.UnimplementedWatcherServer
	pb.UnimplementedFileMoverServer
	pb.UnimplementedContentExtractServer
	pb.UnimplementedQueueServer
	pb.UnimplementedSystemServer

	startTime time.Time
	version   string
	queue     *queue.Queue
	watcher   *watcher.Watcher
}

func New(startTime time.Time, version string, queuePath string) *Server {
	return &Server{
		startTime: startTime,
		version:   version,
		queue:     queue.New(queuePath),
	}
}

// ─── Health ───────────────────────────────────────────

func (s *Server) Ping(_ context.Context, _ *pb.PingRequest) (*pb.PingResponse, error) {
	return &pb.PingResponse{
		Ok:      true,
		UptimeS: time.Since(s.startTime).Seconds(),
		Version: s.version,
	}, nil
}

// ─── Watcher ──────────────────────────────────────────

func (s *Server) Watch(req *pb.WatchRequest, stream pb.Watcher_WatchServer) error {
	w, err := watcher.New(5 * time.Second) // 5s debounce for download stability
	if err != nil {
		return status.Errorf(codes.Internal, "failed to create watcher: %v", err)
	}
	s.watcher = w
	defer w.Stop()

	eventCh := make(chan *pb.FSEvent, 100)
	if err := w.Watch(req.Paths, req.IgnorePatterns, req.Recursive, eventCh); err != nil {
		return status.Errorf(codes.Internal, "failed to start watching: %v", err)
	}

	for {
		select {
		case <-stream.Context().Done():
			return nil
		case evt, ok := <-eventCh:
			if !ok {
				return nil
			}
			if err := stream.Send(evt); err != nil {
				// Python disconnected — buffer events
				s.queue.Push(evt)
				return err
			}
		}
	}
}

func (s *Server) StopWatch(_ context.Context, _ *pb.StopWatchRequest) (*pb.StopWatchResponse, error) {
	if s.watcher != nil {
		s.watcher.Stop()
		s.watcher = nil
	}
	return &pb.StopWatchResponse{Ok: true}, nil
}

// ─── FileMover ────────────────────────────────────────

func (s *Server) Move(_ context.Context, req *pb.MoveRequest) (*pb.MoveResponse, error) {
	// v1 invariant: never overwrite
	if req.Overwrite {
		return &pb.MoveResponse{
			Ok:    false,
			Error: "overwrite=true is not allowed in v1",
		}, nil
	}

	size, checksum, err := mover.Move(req.Src, req.Dst, false, req.DryRun)
	if err != nil {
		return &pb.MoveResponse{
			Ok:    false,
			Error: err.Error(),
			Src:   req.Src,
			Dst:   req.Dst,
		}, nil
	}

	return &pb.MoveResponse{
		Ok:        true,
		Src:       req.Src,
		Dst:       req.Dst,
		SizeBytes: size,
		Checksum:  checksum,
		WasDryRun: req.DryRun,
	}, nil
}

func (s *Server) Copy(_ context.Context, req *pb.CopyRequest) (*pb.CopyResponse, error) {
	if req.Overwrite {
		return &pb.CopyResponse{
			Ok:    false,
			Error: "overwrite=true is not allowed in v1",
		}, nil
	}

	size, checksum, err := mover.Copy(req.Src, req.Dst, false, req.DryRun)
	if err != nil {
		return &pb.CopyResponse{
			Ok:    false,
			Error: err.Error(),
			Src:   req.Src,
			Dst:   req.Dst,
		}, nil
	}

	return &pb.CopyResponse{
		Ok:        true,
		Src:       req.Src,
		Dst:       req.Dst,
		SizeBytes: size,
		Checksum:  checksum,
		WasDryRun: req.DryRun,
	}, nil
}

// ─── ContentExtract (Phase 2+) ───────────────────────

func (s *Server) PreviewText(_ context.Context, _ *pb.PreviewTextRequest) (*pb.PreviewTextResponse, error) {
	return nil, status.Error(codes.Unimplemented, "PreviewText not implemented — Phase 2")
}

func (s *Server) ExtractPdfText(_ context.Context, _ *pb.ExtractPdfTextRequest) (*pb.ExtractPdfTextResponse, error) {
	return nil, status.Error(codes.Unimplemented, "ExtractPdfText not implemented — Phase 2")
}

func (s *Server) ProbeMime(_ context.Context, _ *pb.ProbeMimeRequest) (*pb.ProbeMimeResponse, error) {
	return nil, status.Error(codes.Unimplemented, "ProbeMime not implemented — Phase 2")
}

// ─── Queue ────────────────────────────────────────────

func (s *Server) Drain(_ context.Context, req *pb.DrainRequest) (*pb.DrainResponse, error) {
	events := s.queue.Drain(req.MaxEvents)
	return &pb.DrainResponse{Events: events}, nil
}

func (s *Server) Stats(_ context.Context, _ *pb.QueueStatsRequest) (*pb.QueueStatsResponse, error) {
	return &pb.QueueStatsResponse{
		Buffered:  s.queue.Len(),
		TotalSeen: s.queue.TotalSeen(),
		OldestMs:  s.queue.OldestMs(),
	}, nil
}

// ─── System ───────────────────────────────────────────

func (s *Server) Manifest(_ context.Context, _ *pb.ManifestRequest) (*pb.ManifestResponse, error) {
	m, err := manifest.Collect()
	if err != nil {
		return &pb.ManifestResponse{Ok: false, Error: err.Error()}, nil
	}
	data, err := m.ToJSON()
	if err != nil {
		return &pb.ManifestResponse{Ok: false, Error: err.Error()}, nil
	}
	return &pb.ManifestResponse{Ok: true, Json: string(data)}, nil
}

func (s *Server) CheckMount(_ context.Context, req *pb.CheckMountRequest) (*pb.CheckMountResponse, error) {
	mounted := health.CheckMount(req.Path)
	freeBytes := health.DiskFreeBytes(req.Path)
	return &pb.CheckMountResponse{Mounted: mounted, FreeBytes: freeBytes}, nil
}
