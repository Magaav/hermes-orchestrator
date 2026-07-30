package studio

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"visao/backend/internal/auth"
)

type TokenUsage struct {
	Available              bool  `json:"available"`
	Complete               bool  `json:"complete"`
	MainInputTokens        int64 `json:"main_input_tokens"`
	CachedMainInputTokens  int64 `json:"cached_main_input_tokens"`
	MainOutputTokens       int64 `json:"main_output_tokens"`
	ReasoningOutputTokens  int64 `json:"reasoning_output_tokens"`
	ImageInputTokens       int64 `json:"image_input_tokens"`
	ImageOutputTokens      int64 `json:"image_output_tokens"`
	ImageTextInputTokens   int64 `json:"image_text_input_tokens"`
	ImageSourceInputTokens int64 `json:"image_source_input_tokens"`
	TotalTokens            int64 `json:"total_tokens"`
}

type UsageRecord struct {
	TraceID       string
	ResponseID    string
	UserID        int64
	UserName      string
	SourceName    string
	ProviderModel string
	CreatedAt     time.Time
	Usage         TokenUsage
}

type UsageSummary struct {
	Pictures           int   `json:"pictures"`
	MeteredPictures    int   `json:"meteredPictures"`
	CompletePictures   int   `json:"completePictures"`
	PartialPictures    int   `json:"partialPictures"`
	UnreportedPictures int   `json:"unreportedPictures"`
	TotalTokens        int64 `json:"totalTokens"`
	AverageTokens      int64 `json:"averageTokens"`
	MainTokens         int64 `json:"mainTokens"`
	ImageTokens        int64 `json:"imageTokens"`
}

type UsagePoint struct {
	Key      string `json:"key"`
	Label    string `json:"label"`
	Tokens   int64  `json:"tokens"`
	Pictures int    `json:"pictures"`
}

type UserUsage struct {
	ID              int64  `json:"id"`
	Name            string `json:"name"`
	Pictures        int    `json:"pictures"`
	MeteredPictures int    `json:"meteredPictures"`
	TotalTokens     int64  `json:"totalTokens"`
	AverageTokens   int64  `json:"averageTokens"`
}

type UsageRange struct {
	From     string `json:"from"`
	To       string `json:"to"`
	Label    string `json:"label"`
	Previous string `json:"previous"`
	Next     string `json:"next"`
}

type UsageDashboard struct {
	Period  string       `json:"period"`
	Scope   string       `json:"scope"`
	Anchor  string       `json:"anchor"`
	Range   UsageRange   `json:"range"`
	Summary UsageSummary `json:"summary"`
	Series  []UsagePoint `json:"series"`
	Users   []UserUsage  `json:"users"`
}

type UsageStore struct {
	db       *sql.DB
	location *time.Location
	now      func() time.Time
}

var contextInvalidAnchor = errors.New("invalid Studio usage anchor")

func NewUsageStore(ctx context.Context, db *sql.DB, location *time.Location) (*UsageStore, error) {
	if db == nil {
		return nil, errors.New("studio usage requires a database")
	}
	if location == nil {
		location = time.UTC
	}
	store := &UsageStore{db: db, location: location, now: time.Now}
	if err := store.migrate(ctx); err != nil {
		return nil, err
	}
	return store, nil
}

func (s *UsageStore) migrate(ctx context.Context) error {
	_, err := s.db.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS studio_usage (
			trace_id TEXT PRIMARY KEY,
			response_id TEXT NOT NULL DEFAULT '',
			user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
			user_name TEXT NOT NULL,
			source_name TEXT NOT NULL DEFAULT '',
			provider_model TEXT NOT NULL DEFAULT '',
			created_at TEXT NOT NULL,
			usage_available INTEGER NOT NULL DEFAULT 0,
			usage_complete INTEGER NOT NULL DEFAULT 0,
			main_input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (main_input_tokens >= 0),
			cached_main_input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (cached_main_input_tokens >= 0),
			main_output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (main_output_tokens >= 0),
			reasoning_output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (reasoning_output_tokens >= 0),
			image_input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (image_input_tokens >= 0),
			image_output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (image_output_tokens >= 0),
			image_text_input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (image_text_input_tokens >= 0),
			image_source_input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (image_source_input_tokens >= 0),
			total_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0)
		);
		CREATE INDEX IF NOT EXISTS studio_usage_created_at_idx ON studio_usage(created_at);
		CREATE INDEX IF NOT EXISTS studio_usage_user_created_at_idx ON studio_usage(user_id, created_at);
	`)
	if err != nil {
		return fmt.Errorf("migrate Studio usage: %w", err)
	}
	for _, column := range []struct {
		name        string
		declaration string
	}{
		{"usage_complete", "INTEGER NOT NULL DEFAULT 0"},
		{"image_text_input_tokens", "INTEGER NOT NULL DEFAULT 0 CHECK (image_text_input_tokens >= 0)"},
		{"image_source_input_tokens", "INTEGER NOT NULL DEFAULT 0 CHECK (image_source_input_tokens >= 0)"},
	} {
		if err := s.ensureColumn(ctx, column.name, column.declaration); err != nil {
			return err
		}
	}
	return nil
}

func (s *UsageStore) ensureColumn(ctx context.Context, name, declaration string) error {
	rows, err := s.db.QueryContext(ctx, "PRAGMA table_info(studio_usage)")
	if err != nil {
		return fmt.Errorf("inspect Studio usage columns: %w", err)
	}
	found := false
	for rows.Next() {
		var cid, notNull, primaryKey int
		var columnName, columnType string
		var defaultValue any
		if err := rows.Scan(&cid, &columnName, &columnType, &notNull, &defaultValue, &primaryKey); err != nil {
			_ = rows.Close()
			return fmt.Errorf("read Studio usage columns: %w", err)
		}
		if columnName == name {
			found = true
		}
	}
	if err := rows.Close(); err != nil {
		return fmt.Errorf("close Studio usage columns: %w", err)
	}
	if found {
		return nil
	}
	if _, err := s.db.ExecContext(ctx, "ALTER TABLE studio_usage ADD COLUMN "+name+" "+declaration); err != nil {
		return fmt.Errorf("add Studio usage column %s: %w", name, err)
	}
	return nil
}

func (s *UsageStore) Record(ctx context.Context, record UsageRecord) error {
	record.TraceID = strings.TrimSpace(record.TraceID)
	if record.TraceID == "" || record.UserID <= 0 {
		return errors.New("invalid Studio usage record")
	}
	if record.CreatedAt.IsZero() {
		record.CreatedAt = s.now()
	}
	usage := nonNegativeUsage(record.Usage)
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO studio_usage (
			trace_id, response_id, user_id, user_name, source_name, provider_model, created_at,
			usage_available, usage_complete, main_input_tokens, cached_main_input_tokens, main_output_tokens,
			reasoning_output_tokens, image_input_tokens, image_output_tokens, image_text_input_tokens,
			image_source_input_tokens, total_tokens
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(trace_id) DO NOTHING
	`, record.TraceID, strings.TrimSpace(record.ResponseID), record.UserID, bounded(record.UserName, 160),
		bounded(record.SourceName, 180), bounded(record.ProviderModel, 120),
		record.CreatedAt.UTC().Format(time.RFC3339Nano), usage.Available, usage.Complete,
		usage.MainInputTokens, usage.CachedMainInputTokens, usage.MainOutputTokens,
		usage.ReasoningOutputTokens, usage.ImageInputTokens, usage.ImageOutputTokens,
		usage.ImageTextInputTokens, usage.ImageSourceInputTokens, usage.TotalTokens)
	if err != nil {
		return fmt.Errorf("record Studio usage: %w", err)
	}
	return nil
}

func (s *UsageStore) Dashboard(ctx context.Context, user *auth.User, period, scope, anchorValue string) (UsageDashboard, error) {
	if user == nil {
		return UsageDashboard{}, errors.New("Studio usage requires an authenticated user")
	}
	period = strings.ToLower(strings.TrimSpace(period))
	if period != "day" && period != "month" && period != "year" {
		period = "month"
	}
	scope = strings.ToLower(strings.TrimSpace(scope))
	if scope != "all" {
		scope = "me"
	}
	anchor := s.now().In(s.location)
	if anchorValue != "" {
		parsed, err := time.ParseInLocation("2006-01-02", anchorValue, s.location)
		if err != nil {
			return UsageDashboard{}, contextInvalidAnchor
		}
		anchor = parsed
	}
	window := usageWindow(period, anchor, s.location)
	query := `
		SELECT user_id, user_name, created_at, usage_available, usage_complete, main_input_tokens, main_output_tokens,
			image_input_tokens, image_output_tokens, total_tokens
		FROM studio_usage
		WHERE created_at >= ? AND created_at < ?`
	args := []any{window.start.UTC().Format(time.RFC3339Nano), window.end.UTC().Format(time.RFC3339Nano)}
	if scope == "me" {
		query += " AND user_id = ?"
		args = append(args, user.ID)
	}
	rows, err := s.db.QueryContext(ctx, query+" ORDER BY created_at", args...)
	if err != nil {
		return UsageDashboard{}, fmt.Errorf("query Studio usage: %w", err)
	}
	defer rows.Close()

	points := window.points()
	pointIndex := make(map[string]int, len(points))
	for index, point := range points {
		pointIndex[point.Key] = index
	}
	users := map[int64]*UserUsage{}
	summary := UsageSummary{}
	for rows.Next() {
		var userID int64
		var userName, createdValue string
		var available, complete bool
		var mainInput, mainOutput, imageInput, imageOutput, total int64
		if err := rows.Scan(&userID, &userName, &createdValue, &available, &complete, &mainInput, &mainOutput, &imageInput, &imageOutput, &total); err != nil {
			return UsageDashboard{}, err
		}
		created, err := time.Parse(time.RFC3339Nano, createdValue)
		if err != nil {
			continue
		}
		key := window.key(created.In(s.location))
		index, ok := pointIndex[key]
		if !ok {
			continue
		}
		summary.Pictures++
		item := users[userID]
		if item == nil {
			item = &UserUsage{ID: userID, Name: userName}
			users[userID] = item
		}
		item.Pictures++
		if !available {
			summary.UnreportedPictures++
			continue
		}
		summary.MeteredPictures++
		item.MeteredPictures++
		summary.TotalTokens += total
		summary.MainTokens += mainInput + mainOutput
		summary.ImageTokens += imageInput + imageOutput
		points[index].Pictures++
		points[index].Tokens += total
		item.TotalTokens += total
		if complete {
			summary.CompletePictures++
		} else {
			summary.PartialPictures++
		}
	}
	if err := rows.Err(); err != nil {
		return UsageDashboard{}, err
	}
	summary.AverageTokens = roundedAverage(summary.TotalTokens, summary.MeteredPictures)
	userItems := make([]UserUsage, 0, len(users))
	for _, item := range users {
		item.AverageTokens = roundedAverage(item.TotalTokens, item.MeteredPictures)
		userItems = append(userItems, *item)
	}
	sort.Slice(userItems, func(i, j int) bool {
		if userItems[i].TotalTokens == userItems[j].TotalTokens {
			return userItems[i].Name < userItems[j].Name
		}
		return userItems[i].TotalTokens > userItems[j].TotalTokens
	})
	return UsageDashboard{
		Period: period, Scope: scope, Anchor: anchor.Format("2006-01-02"),
		Range: window.rangeValue(), Summary: summary, Series: points, Users: userItems,
	}, nil
}

type dashboardWindow struct {
	period   string
	start    time.Time
	end      time.Time
	previous time.Time
	next     time.Time
}

func usageWindow(period string, anchor time.Time, location *time.Location) dashboardWindow {
	anchor = anchor.In(location)
	switch period {
	case "day":
		start := time.Date(anchor.Year(), anchor.Month(), anchor.Day(), 0, 0, 0, 0, location)
		return dashboardWindow{period: period, start: start, end: start.AddDate(0, 0, 1), previous: start.AddDate(0, 0, -1), next: start.AddDate(0, 0, 1)}
	case "year":
		start := time.Date(anchor.Year(), time.January, 1, 0, 0, 0, 0, location)
		return dashboardWindow{period: period, start: start, end: start.AddDate(1, 0, 0), previous: start.AddDate(-1, 0, 0), next: start.AddDate(1, 0, 0)}
	default:
		start := time.Date(anchor.Year(), anchor.Month(), 1, 0, 0, 0, 0, location)
		return dashboardWindow{period: "month", start: start, end: start.AddDate(0, 1, 0), previous: start.AddDate(0, -1, 0), next: start.AddDate(0, 1, 0)}
	}
}

func (w dashboardWindow) key(value time.Time) string {
	switch w.period {
	case "day":
		return value.Format("2006-01-02T15")
	case "year":
		return value.Format("2006-01")
	default:
		return value.Format("2006-01-02")
	}
}

func (w dashboardWindow) points() []UsagePoint {
	points := []UsagePoint{}
	for cursor := w.start; cursor.Before(w.end); {
		label := cursor.Format("02")
		next := cursor.AddDate(0, 0, 1)
		if w.period == "day" {
			label = cursor.Format("15h")
			next = cursor.Add(time.Hour)
		} else if w.period == "year" {
			label = monthShort(cursor.Month())
			next = cursor.AddDate(0, 1, 0)
		}
		points = append(points, UsagePoint{Key: w.key(cursor), Label: label})
		cursor = next
	}
	return points
}

func (w dashboardWindow) rangeValue() UsageRange {
	label := fmt.Sprintf("%s de %d", monthName(w.start.Month()), w.start.Year())
	if w.period == "day" {
		label = fmt.Sprintf("%02d de %s de %d", w.start.Day(), monthName(w.start.Month()), w.start.Year())
	} else if w.period == "year" {
		label = fmt.Sprintf("%d", w.start.Year())
	}
	return UsageRange{
		From: w.start.Format(time.RFC3339), To: w.end.Format(time.RFC3339), Label: label,
		Previous: w.previous.Format("2006-01-02"), Next: w.next.Format("2006-01-02"),
	}
}

func nonNegativeUsage(usage TokenUsage) TokenUsage {
	values := []*int64{
		&usage.MainInputTokens, &usage.CachedMainInputTokens, &usage.MainOutputTokens,
		&usage.ReasoningOutputTokens, &usage.ImageInputTokens, &usage.ImageOutputTokens, &usage.TotalTokens,
		&usage.ImageTextInputTokens, &usage.ImageSourceInputTokens,
	}
	for _, value := range values {
		if *value < 0 {
			*value = 0
		}
	}
	return usage
}

func roundedAverage(total int64, count int) int64 {
	if count <= 0 {
		return 0
	}
	return (total + int64(count)/2) / int64(count)
}

func bounded(value string, limit int) string {
	value = strings.TrimSpace(value)
	if len(value) > limit {
		return value[:limit]
	}
	return value
}

var months = [...]string{"", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"}
var monthShortNames = [...]string{"", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"}

func monthName(month time.Month) string {
	if month < time.January || month > time.December {
		return ""
	}
	return months[month]
}

func monthShort(month time.Month) string {
	if month < time.January || month > time.December {
		return ""
	}
	return monthShortNames[month]
}
