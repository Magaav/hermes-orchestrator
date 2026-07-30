package control

import (
	"database/sql"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"

	"visao/backend/internal/auth"
)

type HTTP struct {
	store *Store
}

func NewHTTP(store *Store) *HTTP {
	return &HTTP{store: store}
}

func (h *HTTP) Preferences(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFromContext(r.Context())
	if !ok {
		controlError(w, http.StatusUnauthorized, "authentication_required", "Faça login para continuar.")
		return
	}
	if r.Method == http.MethodGet {
		value, err := h.store.Preferences(r.Context(), user.ID)
		if err != nil {
			controlError(w, http.StatusInternalServerError, "preferences_failed", "Não foi possível carregar as preferências.")
			return
		}
		controlJSON(w, http.StatusOK, value)
		return
	}
	var value Preferences
	if err := controlDecode(r, &value, 8<<10); err != nil {
		controlError(w, http.StatusBadRequest, "invalid_preferences", "Preferências inválidas.")
		return
	}
	saved, err := h.store.SavePreferences(r.Context(), user, value)
	if err != nil {
		controlError(w, http.StatusBadRequest, "preferences_failed", "Não foi possível salvar as preferências.")
		return
	}
	controlJSON(w, http.StatusOK, saved)
}

func (h *HTTP) Inventory(w http.ResponseWriter, r *http.Request) {
	value, err := h.store.Inventory(r.Context())
	if err != nil {
		controlError(w, http.StatusInternalServerError, "inventory_failed", "Não foi possível inspecionar o armazenamento.")
		return
	}
	controlJSON(w, http.StatusOK, value)
}

func (h *HTTP) Audit(w http.ResponseWriter, r *http.Request) {
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	items, err := h.store.AuditEntries(r.Context(), limit)
	if err != nil {
		controlError(w, http.StatusInternalServerError, "audit_failed", "Não foi possível carregar os registros.")
		return
	}
	controlJSON(w, http.StatusOK, map[string]any{"items": items, "count": len(items)})
}

func (h *HTTP) Admin(w http.ResponseWriter, r *http.Request) {
	roles, err := h.store.Roles(r.Context())
	if err != nil {
		controlError(w, http.StatusInternalServerError, "roles_failed", "Não foi possível carregar os cargos.")
		return
	}
	users, err := h.store.Users(r.Context())
	if err != nil {
		controlError(w, http.StatusInternalServerError, "users_failed", "Não foi possível carregar os usuários.")
		return
	}
	controlJSON(w, http.StatusOK, map[string]any{
		"capabilities": Capabilities,
		"roles":        roles,
		"users":        users,
	})
}

func (h *HTTP) Roles(w http.ResponseWriter, r *http.Request) {
	user, _ := auth.UserFromContext(r.Context())
	id := r.PathValue("roleID")
	switch r.Method {
	case http.MethodPost, http.MethodPut:
		var input RoleInput
		if err := controlDecode(r, &input, 32<<10); err != nil {
			controlError(w, http.StatusBadRequest, "invalid_role", "Dados do cargo inválidos.")
			return
		}
		if r.Method == http.MethodPost {
			id = ""
		}
		role, err := h.store.SaveRole(r.Context(), user, id, input)
		if err != nil {
			controlError(w, http.StatusBadRequest, "role_failed", err.Error())
			return
		}
		controlJSON(w, map[bool]int{true: http.StatusCreated, false: http.StatusOK}[r.Method == http.MethodPost], role)
	case http.MethodDelete:
		if err := h.store.DeleteRole(r.Context(), user, id); err != nil {
			controlError(w, http.StatusBadRequest, "role_delete_failed", err.Error())
			return
		}
		controlJSON(w, http.StatusOK, map[string]bool{"deleted": true})
	}
}

func (h *HTTP) RoleActions(w http.ResponseWriter, r *http.Request) {
	user, _ := auth.UserFromContext(r.Context())
	var input RoleActionsInput
	if err := controlDecode(r, &input, 32<<10); err != nil {
		controlError(w, http.StatusBadRequest, "invalid_role_actions", "Ações do cargo inválidas.")
		return
	}
	role, err := h.store.SaveRoleActions(r.Context(), user, r.PathValue("roleID"), input)
	if err != nil {
		controlError(w, http.StatusBadRequest, "role_actions_failed", err.Error())
		return
	}
	controlJSON(w, http.StatusOK, role)
}

func (h *HTTP) Users(w http.ResponseWriter, r *http.Request) {
	user, _ := auth.UserFromContext(r.Context())
	switch r.Method {
	case http.MethodPost, http.MethodPut:
		var body struct {
			Email string   `json:"email"`
			Roles []string `json:"roles"`
		}
		if err := controlDecode(r, &body, 16<<10); err != nil {
			controlError(w, http.StatusBadRequest, "invalid_user", "Dados do usuário inválidos.")
			return
		}
		if pathEmail := r.PathValue("email"); pathEmail != "" {
			body.Email = pathEmail
		}
		saved, err := h.store.SaveUser(r.Context(), user, body.Email, body.Roles)
		if err != nil {
			controlError(w, http.StatusBadRequest, "user_failed", err.Error())
			return
		}
		controlJSON(w, http.StatusOK, saved)
	case http.MethodDelete:
		if err := h.store.RevokeUser(r.Context(), user, r.PathValue("email")); err != nil {
			status := http.StatusBadRequest
			if errors.Is(err, sql.ErrNoRows) {
				status = http.StatusNotFound
			}
			controlError(w, status, "user_delete_failed", err.Error())
			return
		}
		controlJSON(w, http.StatusOK, map[string]bool{"deleted": true})
	}
}

func controlDecode(r *http.Request, target any, limit int64) error {
	defer r.Body.Close()
	decoder := json.NewDecoder(io.LimitReader(r.Body, limit+1))
	decoder.DisallowUnknownFields()
	return decoder.Decode(target)
}

func controlJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func controlError(w http.ResponseWriter, status int, code, message string) {
	controlJSON(w, status, map[string]any{"error": code, "message": message})
}
