package submissions

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	_ "modernc.org/sqlite"
)

var ErrNotFound = errors.New("submission not found")

type Submission struct {
	ID          string          `json:"id"`
	Status      string          `json:"status"`
	Atendimento string          `json:"atendimento"`
	Corretor    string          `json:"corretor"`
	Payload     json.RawMessage `json:"payload"`
	CreatedAt   time.Time       `json:"createdAt"`
	UpdatedAt   time.Time       `json:"updatedAt"`
	SubmittedAt *time.Time      `json:"submittedAt,omitempty"`
}

type Summary struct {
	ID          string     `json:"id"`
	Status      string     `json:"status"`
	Atendimento string     `json:"atendimento"`
	Corretor    string     `json:"corretor"`
	CreatedAt   time.Time  `json:"createdAt"`
	UpdatedAt   time.Time  `json:"updatedAt"`
	SubmittedAt *time.Time `json:"submittedAt,omitempty"`
}

type Store struct {
	db       *sql.DB
	location *time.Location
}

func Open(ctx context.Context, path string, location *time.Location) (*Store, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return nil, fmt.Errorf("create data directory: %w", err)
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	for _, pragma := range []string{"PRAGMA journal_mode=WAL", "PRAGMA foreign_keys=ON", "PRAGMA busy_timeout=5000"} {
		if _, err := db.ExecContext(ctx, pragma); err != nil {
			db.Close()
			return nil, fmt.Errorf("configure sqlite: %w", err)
		}
	}
	store := &Store{db: db, location: location}
	if err := store.migrate(ctx); err != nil {
		db.Close()
		return nil, err
	}
	return store, nil
}

func (s *Store) Close() error { return s.db.Close() }

func (s *Store) Connection() *sql.DB { return s.db }

func (s *Store) Ready(ctx context.Context) error { return s.db.PingContext(ctx) }

func (s *Store) migrate(ctx context.Context) error {
	_, err := s.db.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS submissions (
			id TEXT PRIMARY KEY,
			status TEXT NOT NULL CHECK (status IN ('draft', 'submitted')),
			atendimento TEXT NOT NULL DEFAULT '',
			corretor TEXT NOT NULL DEFAULT '',
			payload_json TEXT NOT NULL,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			submitted_at TEXT
		);
		CREATE INDEX IF NOT EXISTS submissions_updated_at_idx ON submissions(updated_at DESC);
	`)
	if err != nil {
		return fmt.Errorf("migrate submissions: %w", err)
	}
	return nil
}

func (s *Store) List(ctx context.Context) ([]Summary, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id, status, atendimento, corretor, created_at, updated_at, submitted_at FROM submissions ORDER BY updated_at DESC LIMIT 200`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]Summary, 0)
	for rows.Next() {
		var item Summary
		var created, updated string
		var submitted sql.NullString
		if err := rows.Scan(&item.ID, &item.Status, &item.Atendimento, &item.Corretor, &created, &updated, &submitted); err != nil {
			return nil, err
		}
		item.CreatedAt = parseTime(created)
		item.UpdatedAt = parseTime(updated)
		if submitted.Valid {
			value := parseTime(submitted.String)
			item.SubmittedAt = &value
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) Get(ctx context.Context, id string) (Submission, error) {
	var item Submission
	var payload, created, updated string
	var submitted sql.NullString
	err := s.db.QueryRowContext(ctx, `SELECT id, status, atendimento, corretor, payload_json, created_at, updated_at, submitted_at FROM submissions WHERE id = ?`, id).
		Scan(&item.ID, &item.Status, &item.Atendimento, &item.Corretor, &payload, &created, &updated, &submitted)
	if errors.Is(err, sql.ErrNoRows) {
		return Submission{}, ErrNotFound
	}
	if err != nil {
		return Submission{}, err
	}
	item.Payload = json.RawMessage(payload)
	item.CreatedAt = parseTime(created)
	item.UpdatedAt = parseTime(updated)
	if submitted.Valid {
		value := parseTime(submitted.String)
		item.SubmittedAt = &value
	}
	return item, nil
}

func (s *Store) Save(ctx context.Context, item Submission) (Submission, error) {
	if item.ID == "" {
		item.ID = randomID()
	}
	if item.Status == "" {
		item.Status = "draft"
	}
	if item.Status != "draft" && item.Status != "submitted" {
		return Submission{}, fmt.Errorf("invalid status")
	}
	if !json.Valid(item.Payload) || len(item.Payload) > 1<<20 {
		return Submission{}, fmt.Errorf("invalid payload")
	}
	now := time.Now().In(s.location).UTC().Truncate(time.Millisecond)
	createdAt := now
	if existing, err := s.Get(ctx, item.ID); err == nil {
		createdAt = existing.CreatedAt
	} else if !errors.Is(err, ErrNotFound) {
		return Submission{}, err
	}
	var submitted any
	if item.Status == "submitted" {
		if item.SubmittedAt == nil {
			item.SubmittedAt = &now
		}
		submitted = item.SubmittedAt.UTC().Format(time.RFC3339Nano)
	}
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO submissions (id, status, atendimento, corretor, payload_json, created_at, updated_at, submitted_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(id) DO UPDATE SET status=excluded.status, atendimento=excluded.atendimento,
			corretor=excluded.corretor, payload_json=excluded.payload_json, updated_at=excluded.updated_at,
			submitted_at=excluded.submitted_at
	`, item.ID, item.Status, strings.TrimSpace(item.Atendimento), strings.TrimSpace(item.Corretor), string(item.Payload), createdAt.Format(time.RFC3339Nano), now.Format(time.RFC3339Nano), submitted)
	if err != nil {
		return Submission{}, err
	}
	return s.Get(ctx, item.ID)
}

func randomID() string {
	bytes := make([]byte, 12)
	if _, err := rand.Read(bytes); err != nil {
		panic(err)
	}
	return hex.EncodeToString(bytes)
}

func parseTime(value string) time.Time {
	parsed, _ := time.Parse(time.RFC3339Nano, value)
	return parsed
}
