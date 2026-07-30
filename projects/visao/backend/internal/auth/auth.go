package auth

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"golang.org/x/oauth2"
	"golang.org/x/oauth2/google"

	"visao/backend/internal/config"
)

const CookieName = "visao_session"

type User struct {
	ID           int64    `json:"id"`
	Email        string   `json:"email"`
	Name         string   `json:"name"`
	Picture      *string  `json:"picture,omitempty"`
	CreatedAt    string   `json:"createdAt"`
	LastLogin    string   `json:"lastLogin"`
	Roles        []string `json:"roles,omitempty"`
	Capabilities []string `json:"capabilities,omitempty"`
}

type userContextKey struct{}

func WithUser(ctx context.Context, user *User) context.Context {
	return context.WithValue(ctx, userContextKey{}, user)
}

func UserFromContext(ctx context.Context) (*User, bool) {
	user, ok := ctx.Value(userContextKey{}).(*User)
	return user, ok && user != nil
}

type Manager struct {
	cfg   config.Config
	db    *sql.DB
	oauth *oauth2.Config
}

func New(ctx context.Context, cfg config.Config, db *sql.DB) (*Manager, error) {
	manager := &Manager{
		cfg: cfg,
		db:  db,
		oauth: &oauth2.Config{
			ClientID:     cfg.GoogleClientID,
			ClientSecret: cfg.GoogleClientSecret,
			RedirectURL:  cfg.GoogleRedirectURL,
			Scopes:       []string{"openid", "email", "profile"},
			Endpoint:     google.Endpoint,
		},
	}
	if err := manager.migrate(ctx); err != nil {
		return nil, err
	}
	if err := manager.seedAllowedEmails(ctx); err != nil {
		return nil, err
	}
	return manager, nil
}

func (m *Manager) StartGoogle(w http.ResponseWriter, r *http.Request) {
	state := randomID(32)
	verifier := oauth2.GenerateVerifier()
	expires := time.Now().Add(10 * time.Minute).UTC().Format(time.RFC3339)
	if _, err := m.db.ExecContext(r.Context(), `INSERT INTO oauth_states(state, verifier, expires_at) VALUES (?, ?, ?)`, state, verifier, expires); err != nil {
		http.Error(w, "oauth_state_error", http.StatusInternalServerError)
		return
	}
	_, _ = m.db.ExecContext(r.Context(), `DELETE FROM oauth_states WHERE expires_at < ?`, time.Now().UTC().Format(time.RFC3339))
	target := m.oauth.AuthCodeURL(state, oauth2.AccessTypeOnline, oauth2.S256ChallengeOption(verifier))
	http.Redirect(w, r, target, http.StatusFound)
}

func (m *Manager) Callback(w http.ResponseWriter, r *http.Request) {
	if providerError := strings.TrimSpace(r.URL.Query().Get("error")); providerError != "" {
		log.Printf("oauth callback provider=google error=%q", providerError)
		http.Redirect(w, r, "/?auth_error=google_cancelled", http.StatusFound)
		return
	}
	state := r.URL.Query().Get("state")
	code := r.URL.Query().Get("code")
	if state == "" || code == "" {
		http.Redirect(w, r, "/?auth_error=missing_code", http.StatusFound)
		return
	}
	verifier, err := m.consumeState(r.Context(), state)
	if err != nil {
		http.Redirect(w, r, "/?auth_error=invalid_state", http.StatusFound)
		return
	}
	token, err := m.oauth.Exchange(r.Context(), code, oauth2.VerifierOption(verifier))
	if err != nil {
		logOAuthExchangeFailure(err)
		http.Redirect(w, r, "/?auth_error=exchange_failed", http.StatusFound)
		return
	}
	profile, err := m.fetchProfile(r.Context(), token)
	if err != nil {
		log.Printf("oauth profile failed provider=google class=%T", err)
		http.Redirect(w, r, "/?auth_error=profile_failed", http.StatusFound)
		return
	}
	if !m.EmailAllowed(profile.Email) {
		log.Printf("oauth access denied provider=google email=%q", profile.Email)
		http.Redirect(w, r, "/?auth_error=email_not_allowed", http.StatusFound)
		return
	}
	user, err := m.upsertUser(r.Context(), profile)
	if err != nil {
		log.Printf("oauth user upsert failed provider=google class=%T", err)
		http.Redirect(w, r, "/?auth_error=user_failed", http.StatusFound)
		return
	}
	if err := m.createSession(w, r.Context(), user.ID); err != nil {
		log.Printf("oauth session failed provider=google class=%T", err)
		http.Redirect(w, r, "/?auth_error=session_failed", http.StatusFound)
		return
	}
	http.Redirect(w, r, "/", http.StatusFound)
}

func (m *Manager) CurrentUser(r *http.Request) (*User, error) {
	cookie, err := r.Cookie(CookieName)
	if err != nil {
		return nil, err
	}
	sessionID, ok := m.verifyCookie(cookie.Value)
	if !ok {
		return nil, errors.New("invalid session signature")
	}
	var user User
	var picture sql.NullString
	err = m.db.QueryRowContext(r.Context(), `
		SELECT u.id, u.email, u.name, COALESCE(NULLIF(u.custom_picture, ''), u.picture), u.created_at, u.last_login_at
		FROM sessions s JOIN users u ON u.id = s.user_id
		WHERE s.id = ? AND s.expires_at > ?
	`, sessionID, time.Now().UTC().Format(time.RFC3339)).Scan(&user.ID, &user.Email, &user.Name, &picture, &user.CreatedAt, &user.LastLogin)
	if err != nil {
		return nil, err
	}
	if !m.EmailAllowed(user.Email) {
		_, _ = m.db.ExecContext(r.Context(), `DELETE FROM sessions WHERE id = ?`, sessionID)
		return nil, errors.New("email no longer allowed")
	}
	if picture.Valid && strings.TrimSpace(picture.String) != "" {
		user.Picture = &picture.String
	}
	return &user, nil
}

func (m *Manager) Logout(w http.ResponseWriter, r *http.Request) {
	if cookie, err := r.Cookie(CookieName); err == nil {
		if sessionID, ok := m.verifyCookie(cookie.Value); ok {
			_, _ = m.db.ExecContext(r.Context(), `DELETE FROM sessions WHERE id = ?`, sessionID)
		}
	}
	http.SetCookie(w, m.expiredCookie())
}

func (m *Manager) EmailAllowed(email string) bool {
	email = strings.ToLower(strings.TrimSpace(email))
	if email == "" {
		return false
	}
	if m.cfg.AuthAllowAllGoogle {
		return true
	}
	var enabled bool
	err := m.db.QueryRow(`SELECT enabled FROM authorized_users WHERE email = ?`, email).Scan(&enabled)
	return err == nil && enabled
}

func (m *Manager) Status() map[string]any {
	var allowedEmailCount int
	_ = m.db.QueryRow(`SELECT COUNT(*) FROM authorized_users WHERE enabled = 1`).Scan(&allowedEmailCount)
	return map[string]any{
		"provider": "google", "configured": m.oauth != nil,
		"redirect": m.cfg.GoogleRedirectURL, "allowAll": m.cfg.AuthAllowAllGoogle,
		"allowedEmailCount": allowedEmailCount,
	}
}

func (m *Manager) migrate(ctx context.Context) error {
	_, err := m.db.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS users (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			google_sub TEXT NOT NULL UNIQUE,
			email TEXT NOT NULL UNIQUE,
			name TEXT NOT NULL,
			picture TEXT,
			created_at TEXT NOT NULL,
			last_login_at TEXT NOT NULL
		);
		CREATE TABLE IF NOT EXISTS sessions (
			id TEXT PRIMARY KEY,
			user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
			expires_at TEXT NOT NULL,
			created_at TEXT NOT NULL
		);
		CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions(expires_at);
		CREATE TABLE IF NOT EXISTS oauth_states (
			state TEXT PRIMARY KEY,
			verifier TEXT NOT NULL,
			expires_at TEXT NOT NULL,
			created_at TEXT NOT NULL DEFAULT (datetime('now'))
		);
		CREATE TABLE IF NOT EXISTS authorized_users (
			email TEXT PRIMARY KEY,
			enabled INTEGER NOT NULL DEFAULT 1,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);
	`)
	if err != nil {
		return fmt.Errorf("migrate auth: %w", err)
	}
	return m.ensureUserColumn(ctx, "custom_picture", "TEXT")
}

func (m *Manager) ensureUserColumn(ctx context.Context, name, declaration string) error {
	rows, err := m.db.QueryContext(ctx, `PRAGMA table_info(users)`)
	if err != nil {
		return err
	}
	found := false
	for rows.Next() {
		var cid, notNull, primaryKey int
		var columnName, columnType string
		var defaultValue any
		if err := rows.Scan(&cid, &columnName, &columnType, &notNull, &defaultValue, &primaryKey); err != nil {
			rows.Close()
			return err
		}
		found = found || columnName == name
	}
	if err := rows.Close(); err != nil {
		return err
	}
	if found {
		return nil
	}
	_, err = m.db.ExecContext(ctx, `ALTER TABLE users ADD COLUMN `+name+` `+declaration)
	return err
}

func (m *Manager) seedAllowedEmails(ctx context.Context) error {
	now := time.Now().UTC().Format(time.RFC3339Nano)
	for _, email := range m.cfg.AuthAllowedEmails {
		if _, err := m.db.ExecContext(ctx, `
			INSERT INTO authorized_users(email, enabled, created_at, updated_at)
			VALUES (?, 1, ?, ?)
			ON CONFLICT(email) DO NOTHING
		`, strings.ToLower(strings.TrimSpace(email)), now, now); err != nil {
			return fmt.Errorf("seed authorized email: %w", err)
		}
	}
	return nil
}

func (m *Manager) consumeState(ctx context.Context, state string) (string, error) {
	tx, err := m.db.BeginTx(ctx, nil)
	if err != nil {
		return "", err
	}
	defer tx.Rollback()
	var verifier, expires string
	if err := tx.QueryRowContext(ctx, `SELECT verifier, expires_at FROM oauth_states WHERE state = ?`, state).Scan(&verifier, &expires); err != nil {
		return "", err
	}
	if _, err := tx.ExecContext(ctx, `DELETE FROM oauth_states WHERE state = ?`, state); err != nil {
		return "", err
	}
	expiresAt, err := time.Parse(time.RFC3339, expires)
	if err != nil || time.Now().After(expiresAt) {
		return "", errors.New("oauth state expired")
	}
	if err := tx.Commit(); err != nil {
		return "", err
	}
	return verifier, nil
}

type googleProfile struct {
	Sub     string `json:"sub"`
	Email   string `json:"email"`
	Name    string `json:"name"`
	Picture string `json:"picture"`
}

func (m *Manager) fetchProfile(ctx context.Context, token *oauth2.Token) (googleProfile, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://www.googleapis.com/oauth2/v3/userinfo", nil)
	if err != nil {
		return googleProfile{}, err
	}
	response, err := m.oauth.Client(ctx, token).Do(request)
	if err != nil {
		return googleProfile{}, err
	}
	defer response.Body.Close()
	if response.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(response.Body, 256))
		return googleProfile{}, fmt.Errorf("Google profile status %d: %s", response.StatusCode, strings.TrimSpace(string(body)))
	}
	var profile googleProfile
	if err := json.NewDecoder(response.Body).Decode(&profile); err != nil {
		return googleProfile{}, err
	}
	if profile.Sub == "" || profile.Email == "" {
		return googleProfile{}, errors.New("Google profile missing subject or email")
	}
	return profile, nil
}

func (m *Manager) upsertUser(ctx context.Context, profile googleProfile) (*User, error) {
	now := time.Now().UTC().Format(time.RFC3339)
	_, err := m.db.ExecContext(ctx, `
		INSERT INTO users(google_sub, email, name, picture, created_at, last_login_at)
		VALUES (?, ?, ?, NULLIF(?, ''), ?, ?)
		ON CONFLICT(email) DO UPDATE SET google_sub=excluded.google_sub, name=excluded.name,
			picture=excluded.picture, last_login_at=excluded.last_login_at
	`, profile.Sub, strings.ToLower(profile.Email), profile.Name, profile.Picture, now, now)
	if err != nil {
		return nil, err
	}
	var user User
	var picture sql.NullString
	if err := m.db.QueryRowContext(ctx, `SELECT id, email, name, COALESCE(NULLIF(custom_picture, ''), picture), created_at, last_login_at FROM users WHERE email = ?`, strings.ToLower(profile.Email)).
		Scan(&user.ID, &user.Email, &user.Name, &picture, &user.CreatedAt, &user.LastLogin); err != nil {
		return nil, err
	}
	if picture.Valid {
		user.Picture = &picture.String
	}
	return &user, nil
}

func (m *Manager) createSession(w http.ResponseWriter, ctx context.Context, userID int64) error {
	sessionID := randomID(36)
	expires := time.Now().Add(30 * 24 * time.Hour).UTC()
	if _, err := m.db.ExecContext(ctx, `INSERT INTO sessions(id, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)`, sessionID, userID, expires.Format(time.RFC3339), time.Now().UTC().Format(time.RFC3339)); err != nil {
		return err
	}
	http.SetCookie(w, m.cookie(m.signCookie(sessionID), expires))
	return nil
}

func (m *Manager) cookie(value string, expires time.Time) *http.Cookie {
	return &http.Cookie{
		Name: CookieName, Value: value, Path: "/", Expires: expires,
		MaxAge: int(time.Until(expires).Seconds()), HttpOnly: true,
		Secure: m.cfg.SecureCookies, SameSite: http.SameSiteLaxMode,
	}
}

func (m *Manager) expiredCookie() *http.Cookie {
	cookie := m.cookie("", time.Unix(0, 0))
	cookie.MaxAge = -1
	return cookie
}

func (m *Manager) signCookie(sessionID string) string {
	mac := hmac.New(sha256.New, []byte(m.cfg.SessionSecret))
	_, _ = mac.Write([]byte(sessionID))
	return sessionID + "." + hex.EncodeToString(mac.Sum(nil))
}

func (m *Manager) verifyCookie(raw string) (string, bool) {
	sessionID, signature, ok := strings.Cut(raw, ".")
	if !ok || sessionID == "" || signature == "" {
		return "", false
	}
	_, expected, _ := strings.Cut(m.signCookie(sessionID), ".")
	return sessionID, hmac.Equal([]byte(signature), []byte(expected))
}

func randomID(size int) string {
	data := make([]byte, size)
	if _, err := rand.Read(data); err != nil {
		panic(err)
	}
	return hex.EncodeToString(data)
}

func logOAuthExchangeFailure(err error) {
	var retrieval *oauth2.RetrieveError
	if errors.As(err, &retrieval) {
		status := 0
		if retrieval.Response != nil {
			status = retrieval.Response.StatusCode
		}
		log.Printf("oauth exchange failed provider=google status=%d code=%q", status, retrieval.ErrorCode)
		return
	}
	log.Printf("oauth exchange failed provider=google class=%T", err)
}
