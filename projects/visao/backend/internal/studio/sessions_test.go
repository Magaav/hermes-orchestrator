package studio

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestSessionStorePersistsPrivateBeforeAfterAndDeletesAllMemory(t *testing.T) {
	usage, db, location := testUsageStore(t)
	root := filepath.Join(t.TempDir(), "studio-sessions")
	sessions, err := NewSessionStore(context.Background(), db, root, location)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, time.July, 30, 15, 30, 0, 0, location)
	sessions.now = func() time.Time { return now }
	traceID := "trace_session_photo_0001"
	if err := usage.Record(context.Background(), UsageRecord{
		TraceID: traceID, UserID: 1, UserName: "Ana", SourceName: "sala.png",
		ProviderModel: "gpt-5.5",
		Usage: TokenUsage{
			Available: true, MainInputTokens: 100, MainOutputTokens: 20, TotalTokens: 120,
		},
	}); err != nil {
		t.Fatal(err)
	}

	session, err := sessions.Create(context.Background(), 1)
	if err != nil {
		t.Fatal(err)
	}
	photo, err := sessions.AddPhoto(context.Background(), 1, session.ID, SaveSessionPhoto{
		TraceID: traceID, SourceName: "../sala.png", SourceType: "image/png", OutputType: "image/avif",
		ElapsedMS: 12_345,
		Source:    bytes.NewReader(append([]byte("\x89PNG\r\n\x1a\n"), []byte("source")...)),
		Output:    bytes.NewReader(append([]byte{0, 0, 0, 24}, []byte("ftypavifproof")...)),
	})
	if err != nil {
		t.Fatal(err)
	}
	if photo.SourceName != "sala.png" || photo.ElapsedMS != 12_345 || photo.Proof.Usage.TotalTokens != 120 {
		t.Fatalf("unexpected persisted photo: %#v", photo)
	}
	if photo.SourceURL == "" || photo.OutputURL == "" || photo.OutputType != "image/avif" {
		t.Fatalf("missing image contract: %#v", photo)
	}
	if _, err := sessions.Get(context.Background(), 2, session.ID); !errors.Is(err, ErrSessionNotFound) {
		t.Fatalf("another user accessed the session: %v", err)
	}
	output, err := sessions.File(context.Background(), 1, session.ID, photo.ID, "output")
	if err != nil {
		t.Fatal(err)
	}
	if info, err := os.Stat(output.Path); err != nil || info.Size() != photo.OutputBytes {
		t.Fatalf("output was not persisted: info=%v err=%v", info, err)
	}

	if err := sessions.Delete(context.Background(), 1, session.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Dir(output.Path)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("session files remain after delete: %v", err)
	}
	var usageCount int
	if err := db.QueryRow(`SELECT COUNT(*) FROM studio_usage WHERE trace_id = ?`, traceID).Scan(&usageCount); err != nil {
		t.Fatal(err)
	}
	if usageCount != 0 {
		t.Fatalf("session usage remains after delete: %d", usageCount)
	}
}

func TestSessionStoreRejectsUnownedTraceAndInvalidImageContent(t *testing.T) {
	usage, db, location := testUsageStore(t)
	sessions, err := NewSessionStore(context.Background(), db, filepath.Join(t.TempDir(), "sessions"), location)
	if err != nil {
		t.Fatal(err)
	}
	if err := usage.Record(context.Background(), UsageRecord{
		TraceID: "trace_owned_by_bruno", UserID: 2, UserName: "Bruno",
		Usage: TokenUsage{Available: true, TotalTokens: 1},
	}); err != nil {
		t.Fatal(err)
	}
	session, err := sessions.Create(context.Background(), 1)
	if err != nil {
		t.Fatal(err)
	}
	_, err = sessions.AddPhoto(context.Background(), 1, session.ID, SaveSessionPhoto{
		TraceID: "trace_owned_by_bruno", SourceName: "foto.jpg", SourceType: "image/jpeg", OutputType: "image/avif",
		Source: bytes.NewReader([]byte("\xff\xd8\xffsource")),
		Output: bytes.NewReader(append([]byte{0, 0, 0, 24}, []byte("ftypavifproof")...)),
	})
	if !errors.Is(err, ErrSessionNotFound) {
		t.Fatalf("unowned trace was accepted: %v", err)
	}
}
