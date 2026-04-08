package main

import (
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"syscall"
	"time"

	pb "github.com/48Nauts-Operator/antbot-exec/api/gen"
	"github.com/48Nauts-Operator/antbot-exec/internal/server"
	"google.golang.org/grpc"
)

var version = "0.1.0"

func main() {
	socketPath := flag.String("socket", "/tmp/antbot.sock", "Unix socket path for gRPC server")
	queuePath := flag.String("queue", "", "Path for event queue file (default: ~/.antbot/queue.jsonl)")
	flag.Parse()

	if *queuePath == "" {
		home, _ := os.UserHomeDir()
		*queuePath = home + "/.antbot/queue.jsonl"
	}

	// Remove stale socket if present
	if _, err := os.Stat(*socketPath); err == nil {
		if err := os.Remove(*socketPath); err != nil {
			log.Fatalf("failed to remove stale socket %s: %v", *socketPath, err)
		}
	}

	lis, err := net.Listen("unix", *socketPath)
	if err != nil {
		log.Fatalf("failed to listen on %s: %v", *socketPath, err)
	}
	defer os.Remove(*socketPath)

	startTime := time.Now()
	grpcServer := grpc.NewServer()

	// Register services
	svc := server.New(startTime, version, *queuePath)
	pb.RegisterHealthServer(grpcServer, svc)
	pb.RegisterWatcherServer(grpcServer, svc)
	pb.RegisterFileMoverServer(grpcServer, svc)
	pb.RegisterContentExtractServer(grpcServer, svc)
	pb.RegisterQueueServer(grpcServer, svc)

	// Graceful shutdown
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigCh
		fmt.Println("\nshutting down...")
		grpcServer.GracefulStop()
	}()

	log.Printf("antbot-exec %s listening on %s", version, *socketPath)
	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("gRPC server error: %v", err)
	}
}
