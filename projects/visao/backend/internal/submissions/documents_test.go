package submissions

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestDocumentsZIPContainsEveryReferencedPDFOnce(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	store, err := Open(ctx, filepath.Join(root, "test.sqlite3"), time.UTC)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	uploads := filepath.Join(root, "uploads")
	if err := os.MkdirAll(uploads, 0o750); err != nil {
		t.Fatal(err)
	}
	firstID := "111111111111111111111111"
	secondID := "222222222222222222222222"
	if err := os.WriteFile(filepath.Join(uploads, firstID+".pdf"), []byte("%PDF-first"), 0o640); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(uploads, secondID+".pdf"), []byte("%PDF-second"), 0o640); err != nil {
		t.Fatal(err)
	}
	payload := json.RawMessage(`{
		"version":1,
		"values":{"meta.atendimento":"A-1","meta.corretor":"Ana"},
		"checklist":{
			"seller":{"files":[{"id":"222222222222222222222222","name":"Contrato: final.pdf"}]},
			"buyer":{"files":[{"id":"111111111111111111111111","name":"Documento.pdf"},{"id":"111111111111111111111111","name":"Duplicado.pdf"}]}
		}
	}`)
	item, err := store.Save(ctx, Submission{Status: "draft", Atendimento: "A-1", Corretor: "Ana", Payload: payload})
	if err != nil {
		t.Fatal(err)
	}
	files, err := store.Documents(ctx, item.ID, uploads)
	if err != nil {
		t.Fatal(err)
	}
	if len(files) != 2 {
		t.Fatalf("expected two unique files, got %#v", files)
	}
	var output bytes.Buffer
	if err := WriteDocumentsZIP(&output, files); err != nil {
		t.Fatal(err)
	}
	reader, err := zip.NewReader(bytes.NewReader(output.Bytes()), int64(output.Len()))
	if err != nil {
		t.Fatal(err)
	}
	if len(reader.File) != 2 || reader.File[0].Name != "01-Documento.pdf" || reader.File[1].Name != "02-Contrato_ final.pdf" {
		t.Fatalf("unexpected archive entries: %#v", reader.File)
	}
	entry, err := reader.File[0].Open()
	if err != nil {
		t.Fatal(err)
	}
	content, err := io.ReadAll(entry)
	_ = entry.Close()
	if err != nil || string(content) != "%PDF-first" {
		t.Fatalf("unexpected first document: %q err=%v", content, err)
	}
}
