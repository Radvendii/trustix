// Copyright (C) 2022 adisbladis
// Copyright © 2020-2022 The Trustix Authors
//
// SPDX-License-Identifier: GPL-3.0-only

package eval

import (
	"fmt"
	"github.com/pbnjay/memory"
	"strconv"
)

type EvalConfig struct {
	Expr   string
	Arg    map[string]string
	ArgStr map[string]string

	Flake string

	NixPath string

	Workers       int
	MaxMemorySize int

	ResultBufferSize int
}

func NewConfig() *EvalConfig {
	workers := 4
	maxMemorySize := 0

	// Max a rough estimate at a reasonable default evaluator memory usage
	// Each individual worker can still go above the threshold, it's merely the point
	// where they are restarted.
	// This attempts to give each worker about equal ram.
	freeMem := memory.FreeMemory()
	if freeMem > 0 {
		maxMemorySize = int(float64(freeMem/uint64(workers))*0.5) / 1_000_000
	}

	return &EvalConfig{
		Arg:              make(map[string]string),
		ArgStr:           make(map[string]string),
		NixPath:          "",
		Workers:          workers,
		MaxMemorySize:    maxMemorySize,
		ResultBufferSize: 1024,
	}
}

func (c *EvalConfig) AddArg(arg string, value string) {
	delete(c.Arg, arg)
	delete(c.ArgStr, arg)
	c.Arg[arg] = value
}

func (c *EvalConfig) AddArgStr(arg string, value string) {
	delete(c.Arg, arg)
	delete(c.ArgStr, arg)
	c.ArgStr[arg] = value
}

func (c *EvalConfig) toArgs() ([]string, error) {

	args := []string{
		"--quiet",
	}

	if c.Flake != "" {
		args = append(args, "--flake", c.Flake)
	}

	for arg, value := range c.Arg {
		args = append(args, "--arg", arg, value)
	}
	for arg, value := range c.ArgStr {
		args = append(args, "--argstr", arg, value)
	}

	if c.Workers > 0 {
		args = append(args, "--workers", strconv.Itoa(c.Workers))
	}

	if c.MaxMemorySize > 0 {
		args = append(args, "--max-memory-size", strconv.Itoa(c.MaxMemorySize))
	}

	if c.Expr == "" {
		return nil, fmt.Errorf("Missing expression to evaluate")
	}
	args = append(args, "--expr", c.Expr)

	return args, nil
}
