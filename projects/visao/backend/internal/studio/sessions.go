package studio

import (
	"bytes"
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const (
	maxSessionPhotos     = 50
	maxSessionSourceSize = 20 << 20
	maxSessionOutputSize = 32 << 20
)

var (
	ErrSessionNotFound = errors.New("Studio session not found")
	ErrSessionFull     = errors.New("Studio session is full")
	validSessionID     = regexp.MustCompile(`^[a-f0-9]{24}$`)
	validTraceID       = regexp.MustCompile(`^[A-Za-z0-9_-]{8,128}$`)
)

type SessionSummary struct {
	ID             string    `json:"id"`
	CreatedAt      time.Time `json:"createdAt"`
	UpdatedAt      time.Time `json:"updatedAt"`
	PhotoCount     int       `json:"photoCount"`
	TotalElapsedMS int64     `json:"totalElapsedMs"`
	TotalBytes     int64     `json:"totalBytes"`
}

type SessionPhotoProof struct {
	TraceID       string     `json:"trace_id"`
	ResponseID    string     `json:"response_id,omitempty"`
	ProviderModel string     `json:"provider_model,omitempty"`
	Usage         TokenUsage `json:"usage"`
}

type SessionPhoto struct {
	ID          string            `json:"id"`
	SourceName  string            `json:"sourceName"`
	SourceType  string            `json:"sourceType"`
	OutputType  string            `json:"outputType"`
	SourceBytes int64             `json:"sourceBytes"`
	OutputBytes int64             `json:"outputBytes"`
	ElapsedMS   int64             `json:"elapsedMs"`
	CreatedAt   time.Time         `json:"createdAt"`
	SourceURL   string            `json:"sourceUrl"`
	OutputURL   string            `json:"outputUrl"`
	Proof       SessionPhotoProof `json:"proof"`
}

type StudioSession struct {
	SessionSummary
	Photos []SessionPhoto `json:"photos"`
}

type SaveSessionPhoto struct {
	TraceID    string
	SourceName string
	SourceType string
	OutputType string
	ElapsedMS  int64
	Source     io.Reader
	Output     io.Reader
}

type SessionFile struct {
	Path      string
	MediaType string
	Name      string
}

type SessionStore struct {
	db       *sql.DB
	root     string
	location *time.Location
	now      func() time.Time
}

func NewSessionStore(ctx context.Context, db *sql.DB, root string, location *time.Location) (*SessionStore, error) {
	if db == nil {
		return nil, errors.New("Studio sessions require a database")
	}
	if location == nil {
		location = time.UTC
	}
	root = filepath.Clean(strings.TrimSpace(root))
	if root == "" || !filepath.IsAbs(root) {
		return nil, errors.New("Studio sessions require an absolute storage directory")
	}
	if err := os.MkdirAll(root, 0o750); err != nil {
		return nil, fmt.Errorf("create Studio session directory: %w", err)
	}
	store := &SessionStore{db: db, root: root, location: location, now: time.Now}
	if err := store.migrate(ctx); err != nil {
		return nil, err
	}
	return store, nil
}

func (s *SessionStore) migrate(ctx context.Context) error {
	_, err := s.db.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS studio_sessions (
			id TEXT PRIMARY KEY,
			user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);
		CREATE INDEX IF NOT EXISTS studio_sessions_user_updated_idx
			ON studio_sessions(user_id, updated_at DESC);
		CREATE TABLE IF NOT EXISTS studio_session_photos (
			id TEXT PRIMARY KEY,
			session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
			trace_id TEXT NOT NULL,
			source_name TEXT NOT NULL,
			source_media_type TEXT NOT NULL,
			output_media_type TEXT NOT NULL,
			source_bytes INTEGER NOT NULL CHECK (source_bytes >= 0),
			output_bytes INTEGER NOT NULL CHECK (output_bytes >= 0),
			elapsed_ms INTEGER NOT NULL CHECK (elapsed_ms >= 0),
			created_at TEXT NOT NULL,
			UNIQUE(session_id, trace_id)
		);
		CREATE INDEX IF NOT EXISTS studio_session_photos_session_created_idx
			ON studio_session_photos(session_id, created_at);
	`)
	if err != nil {
		return fmt.Errorf("migrate Studio sessions: %w", err)
	}
	return nil
}

func (s *SessionStore) Create(ctx context.Context, userID int64) (StudioSession, error) {
	if userID <= 0 {
		return StudioSession{}, errors.New("Studio session requires an authenticated user")
	}
	now := s.now().In(s.location).UTC().Truncate(time.Millisecond)
	id := sessionRandomID()
	if _, err := s.db.ExecContext(ctx, `
		INSERT INTO studio_sessions (id, user_id, created_at, updated_at)
		VALUES (?, ?, ?, ?)
	`, id, userID, now.Format(time.RFC3339Nano), now.Format(time.RFC3339Nano)); err != nil {
		return StudioSession{}, fmt.Errorf("create Studio session: %w", err)
	}
	return s.Get(ctx, userID, id)
}

func (s *SessionStore) List(ctx context.Context, userID int64) ([]SessionSummary, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT s.id, s.created_at, s.updated_at, COUNT(p.id),
			COALESCE(SUM(p.elapsed_ms), 0), COALESCE(SUM(p.output_bytes), 0)
		FROM studio_sessions s
		LEFT JOIN studio_session_photos p ON p.session_id = s.id
		WHERE s.user_id = ?
		GROUP BY s.id
		ORDER BY s.updated_at DESC
		LIMIT 200
	`, userID)
	if err != nil {
		return nil, fmt.Errorf("list Studio sessions: %w", err)
	}
	defer rows.Close()
	items := make([]SessionSummary, 0)
	for rows.Next() {
		item, err := scanSessionSummary(rows)
		if err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *SessionStore) Get(ctx context.Context, userID int64, sessionID string) (StudioSession, error) {
	if !validSessionID.MatchString(sessionID) {
		return StudioSession{}, ErrSessionNotFound
	}
	row := s.db.QueryRowContext(ctx, `
		SELECT s.id, s.created_at, s.updated_at, COUNT(p.id),
			COALESCE(SUM(p.elapsed_ms), 0), COALESCE(SUM(p.output_bytes), 0)
		FROM studio_sessions s
		LEFT JOIN studio_session_photos p ON p.session_id = s.id
		WHERE s.id = ? AND s.user_id = ?
		GROUP BY s.id
	`, sessionID, userID)
	summary, err := scanSessionSummary(row)
	if errors.Is(err, sql.ErrNoRows) {
		return StudioSession{}, ErrSessionNotFound
	}
	if err != nil {
		return StudioSession{}, fmt.Errorf("read Studio session: %w", err)
	}
	rows, err := s.db.QueryContext(ctx, `
		SELECT p.id, p.source_name, p.source_media_type, p.output_media_type,
			p.source_bytes, p.output_bytes, p.elapsed_ms, p.created_at, p.trace_id,
			COALESCE(u.response_id, ''), COALESCE(u.provider_model, ''),
			COALESCE(u.usage_available, 0), COALESCE(u.usage_complete, 0),
			COALESCE(u.main_input_tokens, 0), COALESCE(u.cached_main_input_tokens, 0),
			COALESCE(u.main_output_tokens, 0), COALESCE(u.reasoning_output_tokens, 0),
			COALESCE(u.image_input_tokens, 0), COALESCE(u.image_output_tokens, 0),
			COALESCE(u.image_text_input_tokens, 0), COALESCE(u.image_source_input_tokens, 0),
			COALESCE(u.total_tokens, 0)
		FROM studio_session_photos p
		LEFT JOIN studio_usage u ON u.trace_id = p.trace_id AND u.user_id = ?
		WHERE p.session_id = ?
		ORDER BY p.created_at, p.id
	`, userID, sessionID)
	if err != nil {
		return StudioSession{}, fmt.Errorf("read Studio session photos: %w", err)
	}
	defer rows.Close()
	photos := make([]SessionPhoto, 0, summary.PhotoCount)
	for rows.Next() {
		var photo SessionPhoto
		var created string
		if err := rows.Scan(
			&photo.ID, &photo.SourceName, &photo.SourceType, &photo.OutputType,
			&photo.SourceBytes, &photo.OutputBytes, &photo.ElapsedMS, &created, &photo.Proof.TraceID,
			&photo.Proof.ResponseID, &photo.Proof.ProviderModel,
			&photo.Proof.Usage.Available, &photo.Proof.Usage.Complete,
			&photo.Proof.Usage.MainInputTokens, &photo.Proof.Usage.CachedMainInputTokens,
			&photo.Proof.Usage.MainOutputTokens, &photo.Proof.Usage.ReasoningOutputTokens,
			&photo.Proof.Usage.ImageInputTokens, &photo.Proof.Usage.ImageOutputTokens,
			&photo.Proof.Usage.ImageTextInputTokens, &photo.Proof.Usage.ImageSourceInputTokens,
			&photo.Proof.Usage.TotalTokens,
		); err != nil {
			return StudioSession{}, err
		}
		photo.CreatedAt = sessionParseTime(created)
		base := fmt.Sprintf("/api/studio/sessions/%s/photos/%s", sessionID, photo.ID)
		photo.SourceURL = base + "/source"
		photo.OutputURL = base + "/output"
		photos = append(photos, photo)
	}
	if err := rows.Err(); err != nil {
		return StudioSession{}, err
	}
	return StudioSession{SessionSummary: summary, Photos: photos}, nil
}

func (s *SessionStore) AddPhoto(
	ctx context.Context,
	userID int64,
	sessionID string,
	input SaveSessionPhoto,
) (SessionPhoto, error) {
	input.TraceID = strings.TrimSpace(input.TraceID)
	input.SourceName = sessionSourceName(input.SourceName)
	input.SourceType = strings.ToLower(strings.TrimSpace(input.SourceType))
	input.OutputType = strings.ToLower(strings.TrimSpace(input.OutputType))
	if userID <= 0 || !validSessionID.MatchString(sessionID) || !validTraceID.MatchString(input.TraceID) {
		return SessionPhoto{}, ErrSessionNotFound
	}
	if input.Source == nil || input.Output == nil || input.OutputType != "image/avif" {
		return SessionPhoto{}, errors.New("invalid Studio session photo")
	}
	if input.ElapsedMS < 0 {
		input.ElapsedMS = 0
	}
	if input.ElapsedMS > int64((24*time.Hour)/time.Millisecond) {
		input.ElapsedMS = int64((24 * time.Hour) / time.Millisecond)
	}
	if err := s.authorizeTrace(ctx, userID, sessionID, input.TraceID); err != nil {
		return SessionPhoto{}, err
	}

	photoID := sessionRandomID()
	photoDir := s.photoDir(userID, sessionID, photoID)
	if err := os.MkdirAll(photoDir, 0o750); err != nil {
		return SessionPhoto{}, fmt.Errorf("create Studio photo directory: %w", err)
	}
	cleanup := true
	defer func() {
		if cleanup {
			_ = os.RemoveAll(photoDir)
		}
	}()
	sourcePath := filepath.Join(photoDir, "source")
	outputPath := filepath.Join(photoDir, "output.avif")
	sourceBytes, err := writeSessionImage(sourcePath, input.Source, maxSessionSourceSize, input.SourceType)
	if err != nil {
		return SessionPhoto{}, err
	}
	outputBytes, err := writeSessionImage(outputPath, input.Output, maxSessionOutputSize, "image/avif")
	if err != nil {
		return SessionPhoto{}, err
	}

	now := s.now().In(s.location).UTC().Truncate(time.Millisecond)
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return SessionPhoto{}, err
	}
	defer tx.Rollback()
	var count int
	if err := tx.QueryRowContext(ctx, `
		SELECT COUNT(*) FROM studio_session_photos p
		JOIN studio_sessions s ON s.id = p.session_id
		WHERE p.session_id = ? AND s.user_id = ?
	`, sessionID, userID).Scan(&count); err != nil {
		return SessionPhoto{}, err
	}
	if count >= maxSessionPhotos {
		return SessionPhoto{}, ErrSessionFull
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO studio_session_photos (
			id, session_id, trace_id, source_name, source_media_type, output_media_type,
			source_bytes, output_bytes, elapsed_ms, created_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`, photoID, sessionID, input.TraceID, input.SourceName, input.SourceType, input.OutputType,
		sourceBytes, outputBytes, input.ElapsedMS, now.Format(time.RFC3339Nano)); err != nil {
		return SessionPhoto{}, fmt.Errorf("save Studio session photo: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `
		UPDATE studio_sessions SET updated_at = ? WHERE id = ? AND user_id = ?
	`, now.Format(time.RFC3339Nano), sessionID, userID); err != nil {
		return SessionPhoto{}, err
	}
	if err := tx.Commit(); err != nil {
		return SessionPhoto{}, err
	}
	cleanup = false
	session, err := s.Get(ctx, userID, sessionID)
	if err != nil {
		return SessionPhoto{}, err
	}
	for _, photo := range session.Photos {
		if photo.ID == photoID {
			return photo, nil
		}
	}
	return SessionPhoto{}, errors.New("saved Studio session photo is unavailable")
}

func (s *SessionStore) Delete(ctx context.Context, userID int64, sessionID string) error {
	if !validSessionID.MatchString(sessionID) {
		return ErrSessionNotFound
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var exists int
	if err := tx.QueryRowContext(ctx, `
		SELECT 1 FROM studio_sessions WHERE id = ? AND user_id = ?
	`, sessionID, userID).Scan(&exists); errors.Is(err, sql.ErrNoRows) {
		return ErrSessionNotFound
	} else if err != nil {
		return err
	}
	rows, err := tx.QueryContext(ctx, `
		SELECT trace_id FROM studio_session_photos WHERE session_id = ?
	`, sessionID)
	if err != nil {
		return err
	}
	traceIDs := make([]string, 0)
	for rows.Next() {
		var traceID string
		if err := rows.Scan(&traceID); err != nil {
			_ = rows.Close()
			return err
		}
		traceIDs = append(traceIDs, traceID)
	}
	if err := rows.Close(); err != nil {
		return err
	}

	sessionDir := s.sessionDir(userID, sessionID)
	tombstone := sessionDir + ".deleting-" + sessionRandomID()
	moved := false
	if _, err := os.Stat(sessionDir); err == nil {
		if err := os.Rename(sessionDir, tombstone); err != nil {
			return fmt.Errorf("isolate Studio session files: %w", err)
		}
		moved = true
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	restore := func() {
		if moved {
			_ = os.Rename(tombstone, sessionDir)
		}
	}
	if _, err := tx.ExecContext(ctx, `DELETE FROM studio_sessions WHERE id = ? AND user_id = ?`, sessionID, userID); err != nil {
		restore()
		return err
	}
	for _, traceID := range traceIDs {
		if _, err := tx.ExecContext(ctx, `
			DELETE FROM studio_usage WHERE trace_id = ? AND user_id = ?
		`, traceID, userID); err != nil {
			restore()
			return err
		}
	}
	if err := tx.Commit(); err != nil {
		restore()
		return err
	}
	if moved {
		if err := os.RemoveAll(tombstone); err != nil {
			return fmt.Errorf("remove Studio session files: %w", err)
		}
	}
	return nil
}

func (s *SessionStore) File(
	ctx context.Context,
	userID int64,
	sessionID, photoID, kind string,
) (SessionFile, error) {
	if !validSessionID.MatchString(sessionID) || !validSessionID.MatchString(photoID) {
		return SessionFile{}, ErrSessionNotFound
	}
	var sourceName, sourceType, outputType string
	err := s.db.QueryRowContext(ctx, `
		SELECT p.source_name, p.source_media_type, p.output_media_type
		FROM studio_session_photos p
		JOIN studio_sessions s ON s.id = p.session_id
		WHERE p.id = ? AND p.session_id = ? AND s.user_id = ?
	`, photoID, sessionID, userID).Scan(&sourceName, &sourceType, &outputType)
	if errors.Is(err, sql.ErrNoRows) {
		return SessionFile{}, ErrSessionNotFound
	}
	if err != nil {
		return SessionFile{}, err
	}
	path := filepath.Join(s.photoDir(userID, sessionID, photoID), "source")
	mediaType := sourceType
	name := sourceName
	if kind == "output" {
		path = filepath.Join(s.photoDir(userID, sessionID, photoID), "output.avif")
		mediaType = outputType
		name = strings.TrimSuffix(sourceName, filepath.Ext(sourceName)) + "-studio.avif"
	} else if kind != "source" {
		return SessionFile{}, ErrSessionNotFound
	}
	if _, err := os.Stat(path); err != nil {
		return SessionFile{}, ErrSessionNotFound
	}
	return SessionFile{Path: path, MediaType: mediaType, Name: name}, nil
}

func (s *SessionStore) authorizeTrace(ctx context.Context, userID int64, sessionID, traceID string) error {
	var found int
	err := s.db.QueryRowContext(ctx, `
		SELECT 1
		FROM studio_sessions s
		JOIN studio_usage u ON u.user_id = s.user_id
		WHERE s.id = ? AND s.user_id = ? AND u.trace_id = ?
	`, sessionID, userID, traceID).Scan(&found)
	if errors.Is(err, sql.ErrNoRows) {
		return ErrSessionNotFound
	}
	return err
}

type sessionSummaryScanner interface {
	Scan(...any) error
}

func scanSessionSummary(scanner sessionSummaryScanner) (SessionSummary, error) {
	var item SessionSummary
	var created, updated string
	if err := scanner.Scan(
		&item.ID, &created, &updated, &item.PhotoCount, &item.TotalElapsedMS, &item.TotalBytes,
	); err != nil {
		return SessionSummary{}, err
	}
	item.CreatedAt = sessionParseTime(created)
	item.UpdatedAt = sessionParseTime(updated)
	return item, nil
}

func writeSessionImage(path string, source io.Reader, limit int64, expectedType string) (int64, error) {
	file, err := os.CreateTemp(filepath.Dir(path), ".upload-*")
	if err != nil {
		return 0, err
	}
	temporary := file.Name()
	defer os.Remove(temporary)
	if err := file.Chmod(0o640); err != nil {
		_ = file.Close()
		return 0, err
	}
	written, copyErr := io.Copy(file, io.LimitReader(source, limit+1))
	closeErr := file.Close()
	if copyErr != nil {
		return 0, copyErr
	}
	if closeErr != nil {
		return 0, closeErr
	}
	if written <= 0 || written > limit {
		return 0, errors.New("Studio session image exceeds its limit")
	}
	detected, err := sessionImageType(temporary)
	if err != nil || detected != expectedType {
		return 0, errors.New("Studio session image content is invalid")
	}
	if err := os.Rename(temporary, path); err != nil {
		return 0, err
	}
	return written, nil
}

func sessionImageType(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	header := make([]byte, 16)
	count, err := io.ReadFull(file, header)
	if err != nil && !errors.Is(err, io.ErrUnexpectedEOF) {
		return "", err
	}
	header = header[:count]
	switch {
	case len(header) >= 8 && bytes.Equal(header[:8], []byte("\x89PNG\r\n\x1a\n")):
		return "image/png", nil
	case len(header) >= 3 && bytes.Equal(header[:3], []byte("\xff\xd8\xff")):
		return "image/jpeg", nil
	case len(header) >= 12 && bytes.Equal(header[:4], []byte("RIFF")) && bytes.Equal(header[8:12], []byte("WEBP")):
		return "image/webp", nil
	case len(header) >= 12 && bytes.Equal(header[4:8], []byte("ftyp")) &&
		(bytes.Equal(header[8:12], []byte("avif")) || bytes.Equal(header[8:12], []byte("avis"))):
		return "image/avif", nil
	default:
		return "", errors.New("unsupported Studio session image")
	}
}

func (s *SessionStore) sessionDir(userID int64, sessionID string) string {
	return filepath.Join(s.root, strconv.FormatInt(userID, 10), sessionID)
}

func (s *SessionStore) photoDir(userID int64, sessionID, photoID string) string {
	return filepath.Join(s.sessionDir(userID, sessionID), photoID)
}

func sessionRandomID() string {
	data := make([]byte, 12)
	if _, err := rand.Read(data); err != nil {
		panic(err)
	}
	return hex.EncodeToString(data)
}

func sessionParseTime(value string) time.Time {
	parsed, _ := time.Parse(time.RFC3339Nano, value)
	return parsed
}

func sessionSourceName(value string) string {
	value = filepath.Base(strings.TrimSpace(value))
	value = strings.Map(func(character rune) rune {
		if character < 32 || character == '"' || character == '\\' || character == '/' {
			return -1
		}
		return character
	}, value)
	if value == "" || value == "." {
		return "foto"
	}
	if len(value) > 180 {
		value = value[:180]
	}
	return value
}
