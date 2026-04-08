package server

import (
	"context"
	"time"

	pb "github.com/48Nauts-Operator/antbot-exec/api/gen"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// Server implements all antbot-exec gRPC services.
// Phase 0: only Health is functional; everything else returns Unimplemented.
type Server struct {
	pb.UnimplementedHealthServer
	pb.UnimplementedWatcherServer
	pb.UnimplementedFileMoverServer
	pb.UnimplementedContentExtractServer
	pb.UnimplementedQueueServer

	startTime time.Time
	version   string
}

func New(startTime time.Time, version string) *Server {
	return &Server{startTime: startTime, version: version}
}

// ─── Health (implemented) ─────────────────────────────

func (s *Server) Ping(_ context.Context, _ *pb.PingRequest) (*pb.PingResponse, error) {
	return &pb.PingResponse{
		Ok:      true,
		UptimeS: time.Since(s.startTime).Seconds(),
		Version: s.version,
	}, nil
}

// ─── Watcher (Phase 1) ───────────────────────────────

func (s *Server) Watch(_ *pb.WatchRequest, _ pb.Watcher_WatchServer) error {
	return status.Error(codes.Unimplemented, "Watch not implemented — Phase 1")
}

func (s *Server) StopWatch(_ context.Context, _ *pb.StopWatchRequest) (*pb.StopWatchResponse, error) {
	return nil, status.Error(codes.Unimplemented, "StopWatch not implemented — Phase 1")
}

// ─── FileMover (Phase 1) ─────────────────────────────

func (s *Server) Move(_ context.Context, _ *pb.MoveRequest) (*pb.MoveResponse, error) {
	return nil, status.Error(codes.Unimplemented, "Move not implemented — Phase 1")
}

func (s *Server) Copy(_ context.Context, _ *pb.CopyRequest) (*pb.CopyResponse, error) {
	return nil, status.Error(codes.Unimplemented, "Copy not implemented — Phase 1")
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

// ─── Queue (Phase 1) ─────────────────────────────────

func (s *Server) Drain(_ context.Context, _ *pb.DrainRequest) (*pb.DrainResponse, error) {
	return nil, status.Error(codes.Unimplemented, "Drain not implemented — Phase 1")
}

func (s *Server) Stats(_ context.Context, _ *pb.QueueStatsRequest) (*pb.QueueStatsResponse, error) {
	return nil, status.Error(codes.Unimplemented, "Stats not implemented — Phase 1")
}
