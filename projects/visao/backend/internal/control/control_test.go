package control

import (
	"context"
	"database/sql"
	"encoding/json"
	"path/filepath"
	"testing"
	"time"

	_ "modernc.org/sqlite"

	"visao/backend/internal/auth"
	"visao/backend/internal/config"
)

func testStore(t *testing.T) (*Store, *sql.DB, *auth.User) {
	t.Helper()
	db, err := sql.Open("sqlite", "file:"+t.Name()+"?mode=memory&cache=shared")
	if err != nil {
		t.Fatal(err)
	}
	db.SetMaxOpenConns(1)
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Exec(`
		PRAGMA foreign_keys=ON;
		CREATE TABLE users (
			id INTEGER PRIMARY KEY, google_sub TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE,
			name TEXT NOT NULL, picture TEXT, custom_picture TEXT, created_at TEXT NOT NULL, last_login_at TEXT NOT NULL
		);
		CREATE TABLE authorized_users (
			email TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1,
			created_at TEXT NOT NULL, updated_at TEXT NOT NULL
		);
		INSERT INTO users VALUES (1, 'owner-sub', 'owner@example.com', 'Owner', NULL, NULL, '2026-07-30T00:00:00Z', '2026-07-30T00:00:00Z');
		INSERT INTO authorized_users VALUES ('owner@example.com', 1, '2026-07-30T00:00:00Z', '2026-07-30T00:00:00Z');
	`); err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	store, err := New(context.Background(), db, config.Config{
		AuthAllowedEmails:  []string{"owner@example.com"},
		AccessOwnerEmail:   "owner@example.com",
		ProjectRoot:        root,
		DBPath:             filepath.Join(root, "data", "visao.sqlite3"),
		UploadsDir:         filepath.Join(root, "data", "uploads"),
		StudioSessionsDir:  filepath.Join(root, "data", "studio-sessions"),
		ProfilePicturesDir: filepath.Join(root, "data", "profile-pictures"),
		FrontendDist:       filepath.Join(root, "frontend", "dist"),
		Location:           time.UTC,
	})
	if err != nil {
		t.Fatal(err)
	}
	return store, db, &auth.User{ID: 1, Email: "owner@example.com", Name: "Owner"}
}

func TestProfilePicturePersistsFileAndAudit(t *testing.T) {
	store, db, owner := testStore(t)
	png := append([]byte{0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'}, make([]byte, 32)...)
	picture, err := store.SaveProfilePicture(context.Background(), owner, png)
	if err != nil {
		t.Fatal(err)
	}
	if picture == "" {
		t.Fatal("profile picture URL is empty")
	}
	file, err := store.ProfilePicture(owner.ID)
	if err != nil || file.MediaType != "image/png" {
		t.Fatalf("unexpected profile file: %#v err=%v", file, err)
	}
	var stored string
	if err := db.QueryRow(`SELECT custom_picture FROM users WHERE id = 1`).Scan(&stored); err != nil || stored != picture {
		t.Fatalf("custom picture was not persisted: %q err=%v", stored, err)
	}
	entries, err := store.AuditEntries(context.Background(), 10)
	if err != nil || len(entries) != 1 || entries[0].Table != "users" {
		t.Fatalf("profile update was not audited: %#v err=%v", entries, err)
	}
}

func TestAccessRolesUsersAndCapabilities(t *testing.T) {
	store, _, owner := testStore(t)
	ctx := context.Background()
	if !store.Allowed(ctx, owner.Email, CapSettingsAdmin) {
		t.Fatal("bootstrap owner is missing admin capability")
	}
	role, err := store.SaveRole(ctx, owner, "", RoleInput{
		Name: "Fotografia", Color: "#123456", Priority: 80,
		Permissions: []string{CapStudioView, CapStudioClean, "unknown.capability"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(role.Permissions) != 0 {
		t.Fatalf("new role inherited actions from its definition: %#v", role.Permissions)
	}
	role, err = store.SaveRoleActions(ctx, owner, role.ID, RoleActionsInput{
		Permissions: []string{CapStudioView, CapStudioClean, "unknown.capability"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(role.Permissions) != 2 {
		t.Fatalf("unexpected actions: %#v", role.Permissions)
	}
	user, err := store.SaveUser(ctx, owner, "photo@example.com", []string{role.ID})
	if err != nil {
		t.Fatal(err)
	}
	if !user.Enabled || !store.Allowed(ctx, user.Email, CapStudioClean) || store.Allowed(ctx, user.Email, CapSettingsAdmin) {
		t.Fatalf("unexpected custom access: %#v", user)
	}
	now := time.Now().UTC().Format(time.RFC3339)
	if _, err := store.db.ExecContext(ctx, `
		INSERT INTO users(id, google_sub, email, name, picture, custom_picture, created_at, last_login_at)
		VALUES (2, 'photo-sub', ?, 'Photo User', 'https://example.com/google.jpg', '/api/profile/picture/2?v=1', ?, ?)
	`, user.Email, now, now); err != nil {
		t.Fatal(err)
	}
	users, err := store.Users(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var managed ManagedUser
	for _, current := range users {
		if current.Email == user.Email {
			managed = current
			break
		}
	}
	if managed.Picture != "/api/profile/picture/2?v=1" {
		t.Fatalf("custom profile picture missing from managed user: %#v", managed)
	}
	if _, err := store.SaveRole(ctx, &auth.User{Email: user.Email}, "", RoleInput{
		Name: "Mesmo nível", Priority: 80, Permissions: []string{CapStudioView},
	}); err == nil {
		t.Fatal("equal-priority role creation was allowed")
	}
	if _, err := store.SaveUser(ctx, owner, "other@example.com", []string{"owner"}); err == nil {
		t.Fatal("owner role delegation was allowed")
	}
	if err := store.RevokeUser(ctx, owner, owner.Email); err == nil {
		t.Fatal("current owner revocation was allowed")
	}
	if _, err := store.db.ExecContext(ctx, `UPDATE authorized_users SET enabled = 0 WHERE email = ?`, user.Email); err != nil {
		t.Fatal(err)
	}
	users, err = store.Users(ctx)
	if err != nil {
		t.Fatal(err)
	}
	for _, current := range users {
		if current.Email == user.Email {
			t.Fatalf("revoked user remained in the authorized list: %#v", current)
		}
	}
}

func TestPreferencesAndAuditRemainProviderReadable(t *testing.T) {
	store, db, owner := testStore(t)
	ctx := context.Background()
	saved, err := store.SavePreferences(ctx, owner, Preferences{Theme: "night", TouchEnabled: false, Notifications: true})
	if err != nil {
		t.Fatal(err)
	}
	if saved.Theme != "night" || saved.TouchEnabled {
		t.Fatalf("unexpected preferences: %#v", saved)
	}
	entries, err := store.AuditEntries(ctx, 20)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || entries[0].Type != "create" || entries[0].Table != "user_preferences" || len(entries[0].JSON) == 0 {
		t.Fatalf("unexpected audit projection: %#v", entries)
	}
	if _, err := db.Exec(`
		INSERT INTO audit_logs(created_at, user_email, user_name, action, table_name, record_id, reason, json_data)
		VALUES ('2026-07-30T00:00:00Z', 'system', 'Sistema', 'update', 'legacy', '1', 'Legado', '{invalid}')
	`); err != nil {
		t.Fatal(err)
	}
	entries, err = store.AuditEntries(ctx, 20)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 2 || !json.Valid(entries[0].JSON) {
		t.Fatalf("invalid legacy JSON broke audit projection: %#v", entries)
	}
}
