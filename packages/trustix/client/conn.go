// Copyright (C) 2021 Tweag IO
// Copyright © 2020-2022 The Trustix Authors
//
// SPDX-License-Identifier: GPL-3.0-only

package client

import (
	"context"
	"net/http"
	"sync"
	"time"

	"github.com/nix-community/trustix/packages/unixtransport"
	log "github.com/sirupsen/logrus"
)

// Use a shared client connection pool
var initOnce sync.Once
var client *http.Client

func CreateClient(URL string) (*Client, error) {
	initOnce.Do(func() {
		t := &http.Transport{}
		unixtransport.Register(t)
		client = &http.Client{Transport: t}
	})

	log.WithFields(log.Fields{
		"address": URL,
	}).Debug("Creating client for remote")

	return &Client{
		LogAPI:  newLogAPIConnectClient(client, URL),
		RpcAPI:  newRpcAPIConnectClient(client, URL),
		NodeAPI: newNodeAPIConnectClient(client, URL),
		LogRPC:  newLogRPCConnectClient(client, URL),
	}, nil
}

// Create a context with the default timeout set
func CreateContext(timeout int) (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), time.Second*time.Duration(timeout))
}
