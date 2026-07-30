package main

import (
	"context"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"visao/backend/internal/config"
	"visao/backend/internal/httpapi"
	"visao/backend/internal/submissions"
)

var buildID = "dev"

func main() {
	envFile := flag.String("env", "", "path to app.env")
	flag.Parse()
	cfg, err := config.Load(*envFile)
	if err != nil {
		log.Fatalf("config: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	store, err := submissions.Open(ctx, cfg.DBPath, cfg.Location)
	cancel()
	if err != nil {
		log.Fatalf("database: %v", err)
	}
	defer store.Close()
	app, err := httpapi.New(cfg, store, buildID)
	if err != nil {
		log.Fatalf("http server: %v", err)
	}
	server := &http.Server{
		Addr:              cfg.Addr(),
		Handler:           app.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
	go func() {
		log.Printf("%s listening on %s", cfg.AppName, cfg.Addr())
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("serve: %v", err)
		}
	}()
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer shutdownCancel()
	_ = server.Shutdown(shutdownCtx)
}
