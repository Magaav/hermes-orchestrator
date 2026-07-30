package submissions

import (
	"context"
	"encoding/json"
	"path/filepath"
	"testing"
	"time"
)

func TestSaveListAndReopenDraft(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "test.sqlite3"), time.UTC)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	payload := json.RawMessage(`{"version":1,"values":{"meta.atendimento":"A-1","meta.corretor":"Ana"},"checklist":{}}`)
	created, err := store.Save(ctx, Submission{Status: "submitted", Atendimento: "A-1", Corretor: "Ana", Payload: payload})
	if err != nil {
		t.Fatal(err)
	}
	if created.ID == "" || created.SubmittedAt == nil {
		t.Fatalf("expected submitted record, got %#v", created)
	}

	reopened, err := store.Save(ctx, Submission{ID: created.ID, Status: "draft", Atendimento: "A-1", Corretor: "Ana", Payload: payload})
	if err != nil {
		t.Fatal(err)
	}
	if reopened.SubmittedAt != nil {
		t.Fatalf("draft must clear submitted timestamp, got %v", reopened.SubmittedAt)
	}
	items, err := store.List(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Status != "draft" {
		t.Fatalf("unexpected list: %#v", items)
	}
}
