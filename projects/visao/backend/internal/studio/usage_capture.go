package studio

import (
	"bytes"
	"encoding/json"
	"path/filepath"
	"strings"

	"visao/backend/internal/auth"
)

const maxUsageFrameBytes = 64 << 10

type usageCapture struct {
	line     []byte
	overflow bool
	detail   *struct {
		SourceName string `json:"source_name"`
		Proof      struct {
			TraceID       string     `json:"trace_id"`
			ResponseID    string     `json:"response_id"`
			ProviderModel string     `json:"provider_model"`
			Usage         TokenUsage `json:"usage"`
		} `json:"proof"`
	}
}

func newUsageCapture() *usageCapture {
	return &usageCapture{line: make([]byte, 0, 4096)}
}

func (c *usageCapture) Write(data []byte) {
	for len(data) > 0 {
		end := bytes.IndexByte(data, '\n')
		if end < 0 {
			c.append(data)
			return
		}
		c.append(data[:end])
		if !c.overflow {
			c.consume()
		}
		c.line = c.line[:0]
		c.overflow = false
		data = data[end+1:]
	}
}

func (c *usageCapture) append(data []byte) {
	if c.overflow {
		return
	}
	if len(c.line)+len(data) > maxUsageFrameBytes {
		c.line = c.line[:0]
		c.overflow = true
		return
	}
	c.line = append(c.line, data...)
}

func (c *usageCapture) consume() {
	if c.detail != nil || !bytes.Contains(c.line, []byte(`"event":"usage"`)) {
		return
	}
	var frame struct {
		Event  string `json:"event"`
		Detail struct {
			SourceName string `json:"source_name"`
			Proof      struct {
				TraceID       string     `json:"trace_id"`
				ResponseID    string     `json:"response_id"`
				ProviderModel string     `json:"provider_model"`
				Usage         TokenUsage `json:"usage"`
			} `json:"proof"`
		} `json:"detail"`
	}
	if json.Unmarshal(c.line, &frame) != nil || frame.Event != "usage" || strings.TrimSpace(frame.Detail.Proof.TraceID) == "" {
		return
	}
	c.detail = &frame.Detail
}

func (c *usageCapture) Record(user *auth.User) (UsageRecord, bool) {
	if c.detail == nil || user == nil {
		return UsageRecord{}, false
	}
	sourceName := filepath.Base(strings.TrimSpace(c.detail.SourceName))
	if sourceName == "." {
		sourceName = ""
	}
	return UsageRecord{
		TraceID:       c.detail.Proof.TraceID,
		ResponseID:    c.detail.Proof.ResponseID,
		UserID:        user.ID,
		UserName:      user.Name,
		SourceName:    sourceName,
		ProviderModel: c.detail.Proof.ProviderModel,
		Usage:         c.detail.Proof.Usage,
	}, true
}
