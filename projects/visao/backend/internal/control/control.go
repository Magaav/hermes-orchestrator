package control

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"visao/backend/internal/auth"
	"visao/backend/internal/config"
)

const (
	CapWorkspaceView       = "workspace.view"
	CapProfileView         = "profile.view"
	CapProfileUpdate       = "profile.update"
	CapAtendimentoView     = "atendimento.view"
	CapAtendimentoWrite    = "atendimento.write"
	CapStudioView          = "studio.view"
	CapStudioClean         = "studio.clean"
	CapStudioSessions      = "studio.sessions"
	CapStudioDashboard     = "studio.dashboard"
	CapStudioSettings      = "studio.settings"
	CapSettingsView        = "settings.view"
	CapSettingsPreferences = "settings.preferences"
	CapSettingsInventory   = "settings.inventory"
	CapSettingsAudit       = "settings.audit"
	CapSettingsAdmin       = "settings.admin"
	CapAdminRolesManage    = "admin.roles.manage"
	CapAdminActionsManage  = "admin.actions.manage"
	CapAdminUsersInvite    = "admin.users.invite"
	CapAdminRolesAssign    = "admin.roles.assign_lower"
	CapAdminUsersRevoke    = "admin.users.revoke_lower"
)

type Capability struct {
	ID    string `json:"id"`
	Label string `json:"label"`
	Group string `json:"group"`
}

var Capabilities = []Capability{
	{CapWorkspaceView, "Abrir espaço de trabalho", "Workspace"},
	{CapProfileView, "Visualizar o próprio perfil", "Workspace"},
	{CapProfileUpdate, "Alterar a própria foto", "Workspace"},
	{CapAtendimentoView, "Visualizar atendimentos", "Atendimento"},
	{CapAtendimentoWrite, "Criar e atualizar atendimentos", "Atendimento"},
	{CapStudioView, "Abrir Studio", "Studio"},
	{CapStudioClean, "Processar imagens", "Studio"},
	{CapStudioSessions, "Gerenciar sessões", "Studio"},
	{CapStudioDashboard, "Visualizar Dashboard", "Studio"},
	{CapStudioSettings, "Configurar Codex", "Studio"},
	{CapSettingsView, "Abrir Configurações", "Configurações"},
	{CapSettingsPreferences, "Alterar preferências", "Configurações"},
	{CapSettingsInventory, "Visualizar banco e arquivos", "Configurações"},
	{CapSettingsAudit, "Visualizar registros CUD", "Configurações"},
	{CapSettingsAdmin, "Gerenciar cargos e usuários", "Admin"},
	{CapAdminRolesManage, "Criar, editar e excluir cargos inferiores", "Admin"},
	{CapAdminActionsManage, "Atribuir ações a cargos inferiores", "Admin"},
	{CapAdminUsersInvite, "Autorizar usuários com cargo inferior", "Admin"},
	{CapAdminRolesAssign, "Atribuir cargos inferiores a usuários", "Admin"},
	{CapAdminUsersRevoke, "Revogar acesso de usuários inferiores", "Admin"},
}

var capabilitySet = func() map[string]bool {
	result := make(map[string]bool, len(Capabilities))
	for _, capability := range Capabilities {
		result[capability.ID] = true
	}
	return result
}()

var memberCapabilities = []string{
	CapWorkspaceView, CapProfileView, CapProfileUpdate, CapAtendimentoView, CapAtendimentoWrite,
	CapStudioView, CapStudioClean, CapStudioSessions, CapStudioDashboard, CapStudioSettings,
	CapSettingsView, CapSettingsPreferences,
}

type Store struct {
	db       *sql.DB
	cfg      config.Config
	location *time.Location
}

type Access struct {
	Roles        []string `json:"roles"`
	Capabilities []string `json:"capabilities"`
}

type Preferences struct {
	Theme         string `json:"theme"`
	TouchEnabled  bool   `json:"touchEnabled"`
	Notifications bool   `json:"notifications"`
}

type Role struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Color       string   `json:"color"`
	Priority    int      `json:"priority"`
	System      bool     `json:"system"`
	Permissions []string `json:"permissions"`
}

type ManagedUser struct {
	Email     string   `json:"email"`
	Enabled   bool     `json:"enabled"`
	Name      string   `json:"name"`
	Picture   string   `json:"picture,omitempty"`
	LastLogin string   `json:"lastLogin,omitempty"`
	Roles     []string `json:"roles"`
}

type AuditEntry struct {
	ID       int64           `json:"id"`
	Date     string          `json:"date"`
	User     string          `json:"user"`
	Type     string          `json:"type"`
	Table    string          `json:"table"`
	RecordID string          `json:"recordId"`
	Reason   string          `json:"reason"`
	JSON     json.RawMessage `json:"json"`
}

type RoleInput struct {
	Name        string   `json:"name"`
	Color       string   `json:"color"`
	Priority    int      `json:"priority"`
	Permissions []string `json:"permissions"`
}

type RoleActionsInput struct {
	Permissions []string `json:"permissions"`
}

func New(ctx context.Context, db *sql.DB, cfg config.Config) (*Store, error) {
	if db == nil {
		return nil, errors.New("control store requires a database")
	}
	store := &Store{db: db, cfg: cfg, location: cfg.Location}
	if store.location == nil {
		store.location = time.UTC
	}
	if err := store.migrate(ctx); err != nil {
		return nil, err
	}
	if err := store.seed(ctx); err != nil {
		return nil, err
	}
	return store, nil
}

func (s *Store) migrate(ctx context.Context) error {
	_, err := s.db.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS access_roles (
			id TEXT PRIMARY KEY,
			name TEXT NOT NULL UNIQUE,
			color TEXT NOT NULL DEFAULT '#005596',
			priority INTEGER NOT NULL DEFAULT 0,
			system INTEGER NOT NULL DEFAULT 0,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);
		CREATE TABLE IF NOT EXISTS access_role_permissions (
			role_id TEXT NOT NULL REFERENCES access_roles(id) ON DELETE CASCADE,
			capability TEXT NOT NULL,
			PRIMARY KEY(role_id, capability)
		);
		CREATE TABLE IF NOT EXISTS access_user_roles (
			email TEXT NOT NULL REFERENCES authorized_users(email) ON DELETE CASCADE,
			role_id TEXT NOT NULL REFERENCES access_roles(id) ON DELETE CASCADE,
			PRIMARY KEY(email, role_id)
		);
		CREATE TABLE IF NOT EXISTS user_preferences (
			user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
			theme TEXT NOT NULL DEFAULT 'day' CHECK(theme IN ('day', 'night')),
			touch_enabled INTEGER NOT NULL DEFAULT 1,
			notifications INTEGER NOT NULL DEFAULT 0,
			updated_at TEXT NOT NULL
		);
		CREATE TABLE IF NOT EXISTS audit_logs (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			created_at TEXT NOT NULL,
			user_id INTEGER,
			user_email TEXT NOT NULL,
			user_name TEXT NOT NULL,
			action TEXT NOT NULL CHECK(action IN ('create', 'update', 'delete')),
			table_name TEXT NOT NULL,
			record_id TEXT NOT NULL,
			reason TEXT NOT NULL,
			json_data TEXT NOT NULL DEFAULT '{}'
		);
		CREATE INDEX IF NOT EXISTS audit_logs_created_at_idx ON audit_logs(created_at DESC);
		CREATE INDEX IF NOT EXISTS audit_logs_table_record_idx ON audit_logs(table_name, record_id);
	`)
	if err != nil {
		return fmt.Errorf("migrate control store: %w", err)
	}
	return nil
}

func (s *Store) seed(ctx context.Context) error {
	now := time.Now().UTC().Format(time.RFC3339Nano)
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	memberCreated := false
	for _, role := range []struct {
		id, name, color string
		priority        int
	}{
		{"owner", "Owner", "#d91a1a", 1000},
		{"member", "Membro", "#005596", 10},
	} {
		result, err := tx.ExecContext(ctx, `
			INSERT INTO access_roles(id, name, color, priority, system, created_at, updated_at)
			VALUES (?, ?, ?, ?, 1, ?, ?) ON CONFLICT(id) DO NOTHING
		`, role.id, role.name, role.color, role.priority, now, now)
		if err != nil {
			return err
		}
		if role.id == "member" {
			affected, _ := result.RowsAffected()
			memberCreated = affected > 0
		}
	}
	for _, capability := range Capabilities {
		if _, err := tx.ExecContext(ctx, `INSERT OR IGNORE INTO access_role_permissions(role_id, capability) VALUES ('owner', ?)`, capability.ID); err != nil {
			return err
		}
	}
	if memberCreated {
		for _, capability := range memberCapabilities {
			if _, err := tx.ExecContext(ctx, `INSERT INTO access_role_permissions(role_id, capability) VALUES ('member', ?)`, capability); err != nil {
				return err
			}
		}
	}
	for _, email := range s.cfg.AuthAllowedEmails {
		email = strings.ToLower(strings.TrimSpace(email))
		if email == "" {
			continue
		}
		if _, err := tx.ExecContext(ctx, `
			INSERT INTO access_user_roles(email, role_id)
			SELECT ?, 'member' WHERE NOT EXISTS (SELECT 1 FROM access_user_roles WHERE email = ?)
		`, email, email); err != nil {
			return err
		}
	}
	ownerEmail := strings.ToLower(strings.TrimSpace(s.cfg.AccessOwnerEmail))
	if ownerEmail != "" {
		if _, err := tx.ExecContext(ctx, `INSERT OR IGNORE INTO access_user_roles(email, role_id) VALUES (?, 'owner')`, ownerEmail); err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, `DELETE FROM access_user_roles WHERE email = ? AND role_id = 'member'`, ownerEmail); err != nil {
			return err
		}
	}
	return tx.Commit()
}

func (s *Store) Access(ctx context.Context, email string) (Access, error) {
	email = strings.ToLower(strings.TrimSpace(email))
	rows, err := s.db.QueryContext(ctx, `
		SELECT r.name, p.capability
		FROM authorized_users au
		JOIN access_user_roles ur ON ur.email = au.email
		JOIN access_roles r ON r.id = ur.role_id
		LEFT JOIN access_role_permissions p ON p.role_id = r.id
		WHERE au.email = ? AND au.enabled = 1
		ORDER BY r.priority DESC, r.name, p.capability
	`, email)
	if err != nil {
		return Access{}, err
	}
	defer rows.Close()
	roleSeen := map[string]bool{}
	capabilitySeen := map[string]bool{}
	result := Access{Roles: []string{}, Capabilities: []string{}}
	for rows.Next() {
		var role string
		var capability sql.NullString
		if err := rows.Scan(&role, &capability); err != nil {
			return Access{}, err
		}
		if !roleSeen[role] {
			roleSeen[role] = true
			result.Roles = append(result.Roles, role)
		}
		if capability.Valid && !capabilitySeen[capability.String] {
			capabilitySeen[capability.String] = true
			result.Capabilities = append(result.Capabilities, capability.String)
		}
	}
	sort.Strings(result.Capabilities)
	return result, rows.Err()
}

func (s *Store) Enrich(ctx context.Context, user *auth.User) error {
	access, err := s.Access(ctx, user.Email)
	if err != nil {
		return err
	}
	user.Roles = access.Roles
	user.Capabilities = access.Capabilities
	return nil
}

func (s *Store) Allowed(ctx context.Context, email, capability string) bool {
	access, err := s.Access(ctx, email)
	if err != nil {
		return false
	}
	for _, current := range access.Capabilities {
		if current == capability {
			return true
		}
	}
	return false
}

func (s *Store) Preferences(ctx context.Context, userID int64) (Preferences, error) {
	result := Preferences{Theme: "day", TouchEnabled: true}
	err := s.db.QueryRowContext(ctx, `SELECT theme, touch_enabled, notifications FROM user_preferences WHERE user_id = ?`, userID).
		Scan(&result.Theme, &result.TouchEnabled, &result.Notifications)
	if errors.Is(err, sql.ErrNoRows) {
		return result, nil
	}
	return result, err
}

func (s *Store) SavePreferences(ctx context.Context, user *auth.User, value Preferences) (Preferences, error) {
	if value.Theme != "day" && value.Theme != "night" {
		return Preferences{}, errors.New("invalid theme")
	}
	var exists int
	_ = s.db.QueryRowContext(ctx, `SELECT COUNT(*) FROM user_preferences WHERE user_id = ?`, user.ID).Scan(&exists)
	now := time.Now().UTC().Format(time.RFC3339Nano)
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO user_preferences(user_id, theme, touch_enabled, notifications, updated_at)
		VALUES (?, ?, ?, ?, ?)
		ON CONFLICT(user_id) DO UPDATE SET theme=excluded.theme, touch_enabled=excluded.touch_enabled,
			notifications=excluded.notifications, updated_at=excluded.updated_at
	`, user.ID, value.Theme, value.TouchEnabled, value.Notifications, now)
	if err != nil {
		return Preferences{}, err
	}
	action := "update"
	if exists == 0 {
		action = "create"
	}
	_ = s.Audit(ctx, user, action, "user_preferences", fmt.Sprint(user.ID), "Preferências do workspace", value)
	return value, nil
}

func (s *Store) Audit(ctx context.Context, user *auth.User, action, table, recordID, reason string, value any) error {
	if action != "create" && action != "update" && action != "delete" {
		return errors.New("invalid audit action")
	}
	raw, err := json.Marshal(value)
	if err != nil {
		raw = []byte(`{}`)
	}
	if len(raw) > 16<<10 {
		raw = []byte(`{"truncated":true}`)
	}
	userID := any(nil)
	email, name := "system", "Sistema"
	if user != nil {
		userID, email, name = user.ID, user.Email, user.Name
	}
	_, err = s.db.ExecContext(ctx, `
		INSERT INTO audit_logs(created_at, user_id, user_email, user_name, action, table_name, record_id, reason, json_data)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
	`, time.Now().UTC().Format(time.RFC3339Nano), userID, email, name, action,
		bounded(table, 80), bounded(recordID, 180), bounded(reason, 240), string(raw))
	return err
}

func (s *Store) AuditEntries(ctx context.Context, limit int) ([]AuditEntry, error) {
	if limit <= 0 || limit > 500 {
		limit = 200
	}
	rows, err := s.db.QueryContext(ctx, `
		SELECT id, created_at, user_name || ' · ' || user_email, action, table_name, record_id, reason, json_data
		FROM audit_logs ORDER BY id DESC LIMIT ?
	`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []AuditEntry{}
	for rows.Next() {
		var item AuditEntry
		var raw string
		if err := rows.Scan(&item.ID, &item.Date, &item.User, &item.Type, &item.Table, &item.RecordID, &item.Reason, &raw); err != nil {
			return nil, err
		}
		item.JSON = json.RawMessage(raw)
		if !json.Valid(item.JSON) {
			item.JSON = json.RawMessage(`{"invalid":true}`)
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) Roles(ctx context.Context) ([]Role, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id, name, color, priority, system FROM access_roles ORDER BY priority DESC, name`)
	if err != nil {
		return nil, err
	}
	items := []Role{}
	for rows.Next() {
		var item Role
		if err := rows.Scan(&item.ID, &item.Name, &item.Color, &item.Priority, &item.System); err != nil {
			rows.Close()
			return nil, err
		}
		items = append(items, item)
	}
	if err := rows.Close(); err != nil {
		return nil, err
	}
	for index := range items {
		permissions, err := s.rolePermissions(ctx, items[index].ID)
		if err != nil {
			return nil, err
		}
		items[index].Permissions = permissions
	}
	return items, nil
}

func (s *Store) rolePermissions(ctx context.Context, roleID string) ([]string, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT capability FROM access_role_permissions WHERE role_id = ? ORDER BY capability`, roleID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []string{}
	for rows.Next() {
		var value string
		if err := rows.Scan(&value); err != nil {
			return nil, err
		}
		result = append(result, value)
	}
	return result, rows.Err()
}

func (s *Store) Users(ctx context.Context) ([]ManagedUser, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT au.email, au.enabled, COALESCE(u.name, ''),
			COALESCE(NULLIF(u.custom_picture, ''), u.picture, ''),
			COALESCE(u.last_login_at, '')
		FROM authorized_users au LEFT JOIN users u ON u.email = au.email
		WHERE au.enabled = 1
		ORDER BY au.email
	`)
	if err != nil {
		return nil, err
	}
	items := []ManagedUser{}
	for rows.Next() {
		var item ManagedUser
		if err := rows.Scan(&item.Email, &item.Enabled, &item.Name, &item.Picture, &item.LastLogin); err != nil {
			rows.Close()
			return nil, err
		}
		items = append(items, item)
	}
	if err := rows.Close(); err != nil {
		return nil, err
	}
	for index := range items {
		item := &items[index]
		roleRows, err := s.db.QueryContext(ctx, `SELECT role_id FROM access_user_roles WHERE email = ? ORDER BY role_id`, item.Email)
		if err != nil {
			return nil, err
		}
		for roleRows.Next() {
			var roleID string
			if err := roleRows.Scan(&roleID); err != nil {
				roleRows.Close()
				return nil, err
			}
			item.Roles = append(item.Roles, roleID)
		}
		if err := roleRows.Close(); err != nil {
			return nil, err
		}
	}
	return items, nil
}

func (s *Store) SaveRole(ctx context.Context, actor *auth.User, id string, input RoleInput) (Role, error) {
	input.Name = strings.TrimSpace(input.Name)
	input.Color = strings.TrimSpace(input.Color)
	if input.Name == "" || len(input.Name) > 80 {
		return Role{}, errors.New("invalid role name")
	}
	if input.Color == "" {
		input.Color = "#005596"
	}
	if input.Priority < 0 || input.Priority >= 1000 {
		return Role{}, errors.New("invalid role priority")
	}
	actorPriority := s.userPriority(ctx, actor)
	if actorPriority <= input.Priority {
		return Role{}, errors.New("role priority must be lower than your own")
	}
	creating := id == ""
	action := "update"
	if creating {
		id = randomID()
		action = "create"
	}
	var system bool
	var currentPriority int
	permissions := []string{}
	if !creating {
		if err := s.db.QueryRowContext(ctx, `SELECT system, priority FROM access_roles WHERE id = ?`, id).Scan(&system, &currentPriority); err != nil {
			return Role{}, errors.New("role not found")
		}
		if system {
			return Role{}, errors.New("system role is immutable")
		}
		if currentPriority >= actorPriority {
			return Role{}, errors.New("cannot edit an equal or higher role")
		}
		var err error
		permissions, err = s.rolePermissions(ctx, id)
		if err != nil {
			return Role{}, err
		}
	}
	now := time.Now().UTC().Format(time.RFC3339Nano)
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return Role{}, err
	}
	defer tx.Rollback()
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO access_roles(id, name, color, priority, system, created_at, updated_at)
		VALUES (?, ?, ?, ?, 0, ?, ?)
		ON CONFLICT(id) DO UPDATE SET name=excluded.name, color=excluded.color,
			priority=excluded.priority, updated_at=excluded.updated_at
	`, id, input.Name, input.Color, input.Priority, now, now); err != nil {
		return Role{}, err
	}
	if err := tx.Commit(); err != nil {
		return Role{}, err
	}
	role := Role{ID: id, Name: input.Name, Color: input.Color, Priority: input.Priority, Permissions: permissions}
	_ = s.Audit(ctx, actor, action, "access_roles", id, "Definição do cargo", role)
	return role, nil
}

func (s *Store) SaveRoleActions(ctx context.Context, actor *auth.User, id string, input RoleActionsInput) (Role, error) {
	if actor == nil {
		return Role{}, errors.New("authentication required")
	}
	var role Role
	if err := s.db.QueryRowContext(ctx, `
		SELECT id, name, color, priority, system FROM access_roles WHERE id = ?
	`, id).Scan(&role.ID, &role.Name, &role.Color, &role.Priority, &role.System); err != nil {
		return Role{}, errors.New("role not found")
	}
	if role.ID == "owner" {
		return Role{}, errors.New("owner actions are immutable")
	}
	if role.Priority >= s.userPriority(ctx, actor) {
		return Role{}, errors.New("cannot edit an equal or higher role")
	}
	permissions := uniquePermissions(input.Permissions)
	access, err := s.Access(ctx, actor.Email)
	if err != nil {
		return Role{}, err
	}
	allowed := make(map[string]bool, len(access.Capabilities))
	for _, capability := range access.Capabilities {
		allowed[capability] = true
	}
	for _, permission := range permissions {
		if !allowed[permission] {
			return Role{}, errors.New("cannot delegate an action you do not have")
		}
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return Role{}, err
	}
	defer tx.Rollback()
	if _, err := tx.ExecContext(ctx, `DELETE FROM access_role_permissions WHERE role_id = ?`, id); err != nil {
		return Role{}, err
	}
	for _, permission := range permissions {
		if _, err := tx.ExecContext(ctx, `INSERT INTO access_role_permissions(role_id, capability) VALUES (?, ?)`, id, permission); err != nil {
			return Role{}, err
		}
	}
	if err := tx.Commit(); err != nil {
		return Role{}, err
	}
	role.Permissions = permissions
	_ = s.Audit(ctx, actor, "update", "access_role_permissions", id, "Ações do cargo atualizadas", role)
	return role, nil
}

func (s *Store) DeleteRole(ctx context.Context, actor *auth.User, id string) error {
	var system bool
	var priority int
	if err := s.db.QueryRowContext(ctx, `SELECT system, priority FROM access_roles WHERE id = ?`, id).Scan(&system, &priority); err != nil {
		return err
	}
	if system {
		return errors.New("system role is immutable")
	}
	if priority >= s.userPriority(ctx, actor) {
		return errors.New("cannot delete an equal or higher role")
	}
	if _, err := s.db.ExecContext(ctx, `DELETE FROM access_roles WHERE id = ?`, id); err != nil {
		return err
	}
	return s.Audit(ctx, actor, "delete", "access_roles", id, "Cargo removido", map[string]string{"id": id})
}

func (s *Store) SaveUser(ctx context.Context, actor *auth.User, email string, roles []string) (ManagedUser, error) {
	email = strings.ToLower(strings.TrimSpace(email))
	if !strings.Contains(email, "@") || len(email) > 254 {
		return ManagedUser{}, errors.New("invalid email")
	}
	if len(roles) == 0 {
		roles = []string{"member"}
	}
	roles = uniqueStrings(roles)
	var existed bool
	_ = s.db.QueryRowContext(ctx, `SELECT enabled FROM authorized_users WHERE email = ?`, email).Scan(&existed)
	if contains(roles, "owner") && (actor == nil || !strings.EqualFold(actor.Email, email)) {
		return ManagedUser{}, errors.New("owner role cannot be delegated")
	}
	if actor != nil && strings.EqualFold(actor.Email, email) {
		var currentOwner int
		_ = s.db.QueryRowContext(ctx, `SELECT COUNT(*) FROM access_user_roles WHERE email = ? AND role_id = 'owner'`, email).Scan(&currentOwner)
		if currentOwner > 0 && !contains(roles, "owner") {
			return ManagedUser{}, errors.New("current owner role cannot be removed")
		}
	}
	actorPriority := s.userPriority(ctx, actor)
	for _, roleID := range roles {
		var priority int
		if err := s.db.QueryRowContext(ctx, `SELECT priority FROM access_roles WHERE id = ?`, roleID).Scan(&priority); err != nil {
			return ManagedUser{}, errors.New("role not found")
		}
		if priority >= actorPriority && (actor == nil || !strings.EqualFold(actor.Email, email) || roleID != "owner") {
			return ManagedUser{}, errors.New("cannot assign an equal or higher role")
		}
	}
	now := time.Now().UTC().Format(time.RFC3339Nano)
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return ManagedUser{}, err
	}
	defer tx.Rollback()
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO authorized_users(email, enabled, created_at, updated_at) VALUES (?, 1, ?, ?)
		ON CONFLICT(email) DO UPDATE SET enabled=1, updated_at=excluded.updated_at
	`, email, now, now); err != nil {
		return ManagedUser{}, err
	}
	if _, err := tx.ExecContext(ctx, `DELETE FROM access_user_roles WHERE email = ?`, email); err != nil {
		return ManagedUser{}, err
	}
	for _, roleID := range roles {
		if _, err := tx.ExecContext(ctx, `INSERT INTO access_user_roles(email, role_id) VALUES (?, ?)`, email, roleID); err != nil {
			return ManagedUser{}, err
		}
	}
	if err := tx.Commit(); err != nil {
		return ManagedUser{}, err
	}
	action, reason := "create", "Acesso autorizado"
	if existed {
		action, reason = "update", "Cargos do usuário atualizados"
	}
	_ = s.Audit(ctx, actor, action, "authorized_users", email, reason, map[string]any{"email": email, "roles": roles})
	return ManagedUser{Email: email, Enabled: true, Roles: roles}, nil
}

func (s *Store) RevokeUser(ctx context.Context, actor *auth.User, email string) error {
	email = strings.ToLower(strings.TrimSpace(email))
	if actor != nil && strings.EqualFold(actor.Email, email) {
		return errors.New("cannot revoke current user")
	}
	if s.emailPriority(ctx, email) >= s.userPriority(ctx, actor) {
		return errors.New("cannot revoke an equal or higher user")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	result, err := tx.ExecContext(ctx, `UPDATE authorized_users SET enabled = 0, updated_at = ? WHERE email = ?`,
		time.Now().UTC().Format(time.RFC3339Nano), email)
	if err != nil {
		return err
	}
	affected, _ := result.RowsAffected()
	if affected == 0 {
		return sql.ErrNoRows
	}
	if _, err := tx.ExecContext(ctx, `DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE email = ?)`, email); err != nil {
		return err
	}
	if err := tx.Commit(); err != nil {
		return err
	}
	return s.Audit(ctx, actor, "delete", "authorized_users", email, "Acesso revogado", map[string]string{"email": email})
}

func uniquePermissions(values []string) []string {
	result := []string{}
	seen := map[string]bool{}
	for _, value := range values {
		value = strings.TrimSpace(value)
		if capabilitySet[value] && !seen[value] {
			seen[value] = true
			result = append(result, value)
		}
	}
	sort.Strings(result)
	return result
}

func uniqueStrings(values []string) []string {
	result := []string{}
	seen := map[string]bool{}
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" && !seen[value] {
			seen[value] = true
			result = append(result, value)
		}
	}
	sort.Strings(result)
	return result
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func (s *Store) userPriority(ctx context.Context, user *auth.User) int {
	if user == nil {
		return -1
	}
	return s.emailPriority(ctx, user.Email)
}

func (s *Store) emailPriority(ctx context.Context, email string) int {
	var priority int
	_ = s.db.QueryRowContext(ctx, `
		SELECT COALESCE(MAX(r.priority), -1)
		FROM access_user_roles ur JOIN access_roles r ON r.id = ur.role_id
		WHERE ur.email = ?
	`, strings.ToLower(strings.TrimSpace(email))).Scan(&priority)
	return priority
}

func bounded(value string, limit int) string {
	value = strings.TrimSpace(value)
	if len(value) > limit {
		return value[:limit]
	}
	return value
}

func randomID() string {
	value := make([]byte, 12)
	if _, err := rand.Read(value); err != nil {
		panic(err)
	}
	return hex.EncodeToString(value)
}
