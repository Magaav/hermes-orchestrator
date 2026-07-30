package auth

import (
	"context"
	"net/http/httptest"
	"path/filepath"
	"testing"
	"time"

	"visao/backend/internal/config"
	"visao/backend/internal/submissions"
)

func TestAllowedEmailAndSessionLifecycle(t *testing.T) {
	ctx := context.Background()
	store, err := submissions.Open(ctx, filepath.Join(t.TempDir(), "auth.sqlite3"), time.UTC)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	cfg := config.Config{
		GoogleClientID: "client", GoogleClientSecret: "secret", GoogleRedirectURL: "https://example.test/auth/google/callback",
		AuthAllowedEmails: []string{"allowed@example.test"}, SessionSecret: "12345678901234567890123456789012", SecureCookies: true,
	}
	manager, err := New(ctx, cfg, store.Connection())
	if err != nil {
		t.Fatal(err)
	}
	if !manager.EmailAllowed("Allowed@Example.Test") || manager.EmailAllowed("outside@example.test") {
		t.Fatal("email allowlist must be case-insensitive and deny unlisted accounts")
	}
	user, err := manager.upsertUser(ctx, googleProfile{Sub: "google-1", Email: "allowed@example.test", Name: "Allowed User"})
	if err != nil {
		t.Fatal(err)
	}
	recorder := httptest.NewRecorder()
	if err := manager.createSession(recorder, ctx, user.ID); err != nil {
		t.Fatal(err)
	}
	cookies := recorder.Result().Cookies()
	if len(cookies) != 1 || !cookies[0].Secure || !cookies[0].HttpOnly || cookies[0].SameSite != 2 {
		t.Fatalf("unexpected session cookie: %#v", cookies)
	}
	request := httptest.NewRequest("GET", "/api/session", nil)
	request.AddCookie(cookies[0])
	current, err := manager.CurrentUser(request)
	if err != nil || current.Email != "allowed@example.test" {
		t.Fatalf("current user failed: user=%#v err=%v", current, err)
	}
	logout := httptest.NewRecorder()
	manager.Logout(logout, request)
	if _, err := manager.CurrentUser(request); err == nil {
		t.Fatal("logout must remove the server-side session")
	}
}
