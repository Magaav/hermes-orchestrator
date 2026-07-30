package submissions

import (
	"archive/zip"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

var (
	ErrNoDocuments     = errors.New("submission has no documents")
	ErrDocumentMissing = errors.New("submission document is missing")
	uploadIDPattern    = regexp.MustCompile(`^[a-f0-9]{24}$`)
)

type DocumentFile struct {
	ID   string
	Name string
	Path string
}

func (s *Store) Documents(ctx context.Context, id, uploadsDir string) ([]DocumentFile, error) {
	item, err := s.Get(ctx, id)
	if err != nil {
		return nil, err
	}
	var payload struct {
		Checklist map[string]struct {
			Files []struct {
				ID   string `json:"id"`
				Name string `json:"name"`
			} `json:"files"`
		} `json:"checklist"`
	}
	if err := json.Unmarshal(item.Payload, &payload); err != nil {
		return nil, err
	}
	keys := make([]string, 0, len(payload.Checklist))
	for key := range payload.Checklist {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	seen := map[string]bool{}
	files := []DocumentFile{}
	for _, key := range keys {
		for _, current := range payload.Checklist[key].Files {
			if !uploadIDPattern.MatchString(current.ID) || seen[current.ID] {
				continue
			}
			seen[current.ID] = true
			path := filepath.Join(uploadsDir, current.ID+".pdf")
			info, err := os.Stat(path)
			if err != nil || !info.Mode().IsRegular() {
				return nil, fmt.Errorf("%w: %s", ErrDocumentMissing, current.ID)
			}
			files = append(files, DocumentFile{ID: current.ID, Name: archiveFileName(current.Name, current.ID), Path: path})
		}
	}
	if len(files) == 0 {
		return nil, ErrNoDocuments
	}
	return files, nil
}

func WriteDocumentsZIP(destination io.Writer, files []DocumentFile) error {
	archive := zip.NewWriter(destination)
	for index, file := range files {
		header := &zip.FileHeader{
			Name:   fmt.Sprintf("%02d-%s", index+1, file.Name),
			Method: zip.Store,
		}
		entry, err := archive.CreateHeader(header)
		if err != nil {
			return err
		}
		source, err := os.Open(file.Path)
		if err != nil {
			return err
		}
		_, copyErr := io.Copy(entry, source)
		closeErr := source.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
	}
	return archive.Close()
}

func archiveFileName(name, id string) string {
	name = strings.TrimSpace(filepath.Base(name))
	if name == "" || name == "." {
		name = "documento-" + id + ".pdf"
	}
	if !strings.HasSuffix(strings.ToLower(name), ".pdf") {
		name += ".pdf"
	}
	var clean strings.Builder
	for _, char := range name {
		if char < 32 || strings.ContainsRune(`<>:"/\|?*`, char) {
			clean.WriteRune('_')
		} else {
			clean.WriteRune(char)
		}
	}
	return clean.String()
}
