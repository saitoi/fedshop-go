package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/pedrosaito/fedshop-go/internal/cli"
)

func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	os.Exit(cli.RunContext(ctx, os.Args[1:], os.Stdout, os.Stderr))
}
