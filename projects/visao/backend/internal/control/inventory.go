package control

import (
	"context"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type Inventory struct {
	GeneratedAt string        `json:"generatedAt"`
	Database    DatabaseInfo  `json:"database"`
	Storage     []StorageArea `json:"storage"`
}

type DatabaseInfo struct {
	Path   string      `json:"path"`
	Bytes  int64       `json:"bytes"`
	Tables []TableInfo `json:"tables"`
}

type TableInfo struct {
	Name    string `json:"name"`
	Rows    int64  `json:"rows"`
	Columns int    `json:"columns"`
}

type StorageArea struct {
	ID        string `json:"id"`
	Label     string `json:"label"`
	Path      string `json:"path"`
	Files     int64  `json:"files"`
	Bytes     int64  `json:"bytes"`
	Available bool   `json:"available"`
}

func (s *Store) Inventory(ctx context.Context) (Inventory, error) {
	database, err := s.databaseInfo(ctx)
	if err != nil {
		return Inventory{}, err
	}
	areas := []struct {
		id, label, path string
	}{
		{"uploads", "Documentos enviados", s.cfg.UploadsDir},
		{"studio-sessions", "Sessões do Studio", s.cfg.StudioSessionsDir},
		{"studio-runtime", "Runtime local do Studio", filepath.Join(s.cfg.ProjectRoot, "data", "studio-runtime")},
		{"profile-pictures", "Fotos de perfil", s.cfg.ProfilePicturesDir},
		{"media", "Mídia do projeto", filepath.Join(s.cfg.ProjectRoot, "media")},
		{"frontend", "Frontend publicado", s.cfg.FrontendDist},
		{"backend", "Backend e binário", filepath.Join(s.cfg.ProjectRoot, "backend")},
	}
	storage := make([]StorageArea, 0, len(areas))
	for _, area := range areas {
		storage = append(storage, s.storageArea(area.id, area.label, area.path))
	}
	return Inventory{
		GeneratedAt: time.Now().In(s.location).Format(time.RFC3339),
		Database:    database,
		Storage:     storage,
	}, nil
}

func (s *Store) databaseInfo(ctx context.Context) (DatabaseInfo, error) {
	result := DatabaseInfo{Path: s.relativePath(s.cfg.DBPath), Tables: []TableInfo{}}
	if info, err := os.Stat(s.cfg.DBPath); err == nil {
		result.Bytes = info.Size()
	}
	rows, err := s.db.QueryContext(ctx, `
		SELECT name FROM sqlite_master
		WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
		ORDER BY name
	`)
	if err != nil {
		return DatabaseInfo{}, err
	}
	defer rows.Close()
	names := []string{}
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return DatabaseInfo{}, err
		}
		names = append(names, name)
	}
	if err := rows.Err(); err != nil {
		return DatabaseInfo{}, err
	}
	for _, name := range names {
		quoted := `"` + strings.ReplaceAll(name, `"`, `""`) + `"`
		var count int64
		if err := s.db.QueryRowContext(ctx, `SELECT COUNT(*) FROM `+quoted).Scan(&count); err != nil {
			return DatabaseInfo{}, fmt.Errorf("count inventory table %s: %w", name, err)
		}
		columnRows, err := s.db.QueryContext(ctx, `PRAGMA table_info(`+quoted+`)`)
		if err != nil {
			return DatabaseInfo{}, err
		}
		columns := 0
		for columnRows.Next() {
			columns++
		}
		if err := columnRows.Close(); err != nil {
			return DatabaseInfo{}, err
		}
		result.Tables = append(result.Tables, TableInfo{Name: name, Rows: count, Columns: columns})
	}
	return result, nil
}

func (s *Store) storageArea(id, label, root string) StorageArea {
	result := StorageArea{ID: id, Label: label, Path: s.relativePath(root)}
	info, err := os.Stat(root)
	if err != nil {
		return result
	}
	result.Available = true
	if !info.IsDir() {
		result.Files = 1
		result.Bytes = info.Size()
		return result
	}
	_ = filepath.WalkDir(root, func(_ string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return nil
		}
		if entry.Type().IsRegular() {
			if current, err := entry.Info(); err == nil {
				result.Files++
				result.Bytes += current.Size()
			}
		}
		return nil
	})
	return result
}

func (s *Store) relativePath(value string) string {
	relative, err := filepath.Rel(s.cfg.ProjectRoot, value)
	if err != nil || strings.HasPrefix(relative, "..") {
		return filepath.Base(value)
	}
	return filepath.ToSlash(relative)
}
