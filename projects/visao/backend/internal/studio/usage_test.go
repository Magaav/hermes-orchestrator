package studio

import (
	"context"
	"database/sql"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	_ "modernc.org/sqlite"

	"visao/backend/internal/auth"
)

func testUsageStore(t *testing.T) (*UsageStore, *sql.DB, *time.Location) {
	t.Helper()
	db, err := sql.Open("sqlite", "file:"+strings.ReplaceAll(t.Name(), "/", "-")+"?mode=memory&cache=shared")
	if err != nil {
		t.Fatal(err)
	}
	db.SetMaxOpenConns(1)
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Exec(`
		PRAGMA foreign_keys=ON;
		CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
		INSERT INTO users (id, name) VALUES (1, 'Ana'), (2, 'Bruno');
	`); err != nil {
		t.Fatal(err)
	}
	location, err := time.LoadLocation("America/Sao_Paulo")
	if err != nil {
		t.Fatal(err)
	}
	store, err := NewUsageStore(context.Background(), db, location)
	if err != nil {
		t.Fatal(err)
	}
	store.now = func() time.Time {
		return time.Date(2026, time.July, 30, 12, 0, 0, 0, location)
	}
	return store, db, location
}

func TestUsageDashboardAggregatesScopeAndNavigablePeriods(t *testing.T) {
	store, _, location := testUsageStore(t)
	records := []UsageRecord{
		{
			TraceID: "trace-july-ana", UserID: 1, UserName: "Ana",
			CreatedAt: time.Date(2026, time.July, 2, 10, 0, 0, 0, location),
			Usage:     TokenUsage{Available: true, Complete: true, MainInputTokens: 40, MainOutputTokens: 20, ImageInputTokens: 10, ImageOutputTokens: 30, TotalTokens: 100},
		},
		{
			TraceID: "trace-july-bruno", UserID: 2, UserName: "Bruno",
			CreatedAt: time.Date(2026, time.July, 2, 11, 0, 0, 0, location),
			Usage:     TokenUsage{Available: true, Complete: true, MainInputTokens: 100, MainOutputTokens: 50, ImageInputTokens: 50, ImageOutputTokens: 100, TotalTokens: 300},
		},
		{
			TraceID: "trace-june-ana", UserID: 1, UserName: "Ana",
			CreatedAt: time.Date(2026, time.June, 12, 9, 0, 0, 0, location),
			Usage:     TokenUsage{Available: true, Complete: true, TotalTokens: 50},
		},
	}
	for _, record := range records {
		if err := store.Record(context.Background(), record); err != nil {
			t.Fatal(err)
		}
	}
	ana := &auth.User{ID: 1, Name: "Ana"}

	everybody, err := store.Dashboard(context.Background(), ana, "month", "all", "2026-07-30")
	if err != nil {
		t.Fatal(err)
	}
	if everybody.Summary.Pictures != 2 || everybody.Summary.TotalTokens != 400 || everybody.Summary.AverageTokens != 200 {
		t.Fatalf("unexpected team summary: %#v", everybody.Summary)
	}
	if len(everybody.Series) != 31 || everybody.Series[1].Tokens != 400 {
		t.Fatalf("unexpected July series: %#v", everybody.Series)
	}
	if len(everybody.Users) != 2 || everybody.Users[0].Name != "Bruno" {
		t.Fatalf("unexpected per-user ranking: %#v", everybody.Users)
	}

	mine, err := store.Dashboard(context.Background(), ana, "month", "me", "2026-07-30")
	if err != nil {
		t.Fatal(err)
	}
	if mine.Summary.Pictures != 1 || mine.Summary.TotalTokens != 100 {
		t.Fatalf("unexpected personal summary: %#v", mine.Summary)
	}

	year, err := store.Dashboard(context.Background(), ana, "year", "me", "2026-07-30")
	if err != nil {
		t.Fatal(err)
	}
	if len(year.Series) != 12 || year.Summary.TotalTokens != 150 || year.Range.Previous != "2025-01-01" || year.Range.Next != "2027-01-01" {
		t.Fatalf("unexpected year window: %#v", year)
	}
}

func TestUsageDashboardIncludesOnlyProviderReportedCounts(t *testing.T) {
	store, _, location := testUsageStore(t)
	for _, record := range []UsageRecord{
		{
			TraceID: "legacy-partial", UserID: 1, UserName: "Ana",
			CreatedAt: time.Date(2026, time.July, 30, 10, 0, 0, 0, location),
			Usage:     TokenUsage{Available: true, TotalTokens: 4102},
		},
		{
			TraceID: "provider-exact", UserID: 1, UserName: "Ana",
			CreatedAt: time.Date(2026, time.July, 30, 11, 0, 0, 0, location),
			Usage:     TokenUsage{Available: true, Complete: true, ImageInputTokens: 100, ImageOutputTokens: 4160, TotalTokens: 4260},
		},
		{
			TraceID: "provider-unreported", UserID: 1, UserName: "Ana",
			CreatedAt: time.Date(2026, time.July, 30, 11, 30, 0, 0, location),
			Usage:     TokenUsage{TotalTokens: 999},
		},
	} {
		if err := store.Record(context.Background(), record); err != nil {
			t.Fatal(err)
		}
	}

	dashboard, err := store.Dashboard(
		context.Background(),
		&auth.User{ID: 1, Name: "Ana"},
		"day",
		"me",
		"2026-07-30",
	)
	if err != nil {
		t.Fatal(err)
	}
	if dashboard.Summary.Pictures != 3 ||
		dashboard.Summary.MeteredPictures != 2 ||
		dashboard.Summary.CompletePictures != 1 ||
		dashboard.Summary.PartialPictures != 1 ||
		dashboard.Summary.UnreportedPictures != 1 ||
		dashboard.Summary.TotalTokens != 8362 ||
		dashboard.Summary.AverageTokens != 4181 {
		t.Fatalf("unexpected provider-reported summary: %#v", dashboard.Summary)
	}
}

func TestUsageCaptureReadsOnlyBoundedServerFrame(t *testing.T) {
	capture := newUsageCapture()
	frame := `{"event":"usage","detail":{"source_name":"apartamento.jpg","proof":{"trace_id":"trace-1","response_id":"response-1","provider_model":"gpt-5.5","usage":{"available":true,"complete":true,"main_input_tokens":12,"main_output_tokens":8,"total_tokens":20}}}}` + "\n"
	capture.Write([]byte(frame[:31]))
	capture.Write([]byte(frame[31:]))
	capture.Write([]byte(`{"event":"complete","detail":{"result":"` + strings.Repeat("a", maxUsageFrameBytes+1) + `"}}` + "\n"))

	record, ok := capture.Record(&auth.User{ID: 9, Name: "Carla"})
	if !ok {
		t.Fatal("usage frame was not captured")
	}
	if record.TraceID != "trace-1" || record.UserID != 9 || record.SourceName != "apartamento.jpg" || record.Usage.TotalTokens != 20 {
		t.Fatalf("unexpected captured record: %#v", record)
	}
}

func TestSuccessfulStreamPersistsUsageForAuthenticatedUser(t *testing.T) {
	store, _, _ := testUsageStore(t)
	handler := &Handler{
		slots: make(chan struct{}, workerLanes),
		usage: store,
		start: func(_ context.Context, _ []byte) (*workerJob, error) {
			wire := `{"event":"usage","detail":{"source_name":"sala.jpg","proof":{"trace_id":"stream-trace","response_id":"response-2","usage":{"available":true,"complete":true,"total_tokens":81}}}}` + "\n" +
				`{"event":"complete","detail":{"chunks":1}}` + "\n"
			return &workerJob{output: io.NopCloser(strings.NewReader(wire)), wait: func() error { return nil }}, nil
		},
	}
	user := &auth.User{ID: 1, Name: "Ana"}
	request := httptest.NewRequest(http.MethodPost, "https://visao.colmeio.com/api/studio/clean", strings.NewReader(validRequest()))
	request.Header.Set("Content-Type", "application/json")
	request = request.WithContext(auth.WithUser(request.Context(), user))
	response := httptest.NewRecorder()

	handler.ServeHTTP(response, request)

	dashboard, err := store.Dashboard(context.Background(), user, "month", "me", "2026-07-30")
	if err != nil {
		t.Fatal(err)
	}
	if response.Code != http.StatusOK || dashboard.Summary.Pictures != 1 || dashboard.Summary.TotalTokens != 81 {
		t.Fatalf("stream usage was not persisted: code=%d summary=%#v", response.Code, dashboard.Summary)
	}
}

func TestUsageDashboardHandlerReturnsCompactAuthenticatedProjection(t *testing.T) {
	store, _, _ := testUsageStore(t)
	if err := store.Record(context.Background(), UsageRecord{
		TraceID: "api-trace", UserID: 1, UserName: "Ana",
		Usage: TokenUsage{Available: true, Complete: true, TotalTokens: 55},
	}); err != nil {
		t.Fatal(err)
	}
	handler := &Handler{usage: store}
	request := httptest.NewRequest(http.MethodGet, "https://visao.colmeio.com/api/studio/usage?period=month&scope=me&anchor=2026-07-30", nil)
	request = request.WithContext(auth.WithUser(request.Context(), &auth.User{ID: 1, Name: "Ana"}))
	response := httptest.NewRecorder()

	handler.UsageDashboard(response, request)

	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"totalTokens":55`) || strings.Contains(response.Body.String(), "source_name") {
		t.Fatalf("unexpected dashboard projection: code=%d body=%s", response.Code, response.Body.String())
	}
}
